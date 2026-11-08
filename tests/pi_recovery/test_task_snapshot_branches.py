import copy
import unittest

from scripts.pi_recovery import maistro_pi_resume as recovery


class BranchTaskTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"type": "session", "version": 3, "id": "session", "cwd": "/example/project"}
        ]
        self.leaf = None
        self.branch(None, "root")
        self.call(
            "create",
            {"action": "create", "subject": "Keep this goal"},
            "Created #1: Keep this goal (pending)",
        )
        self.fork_point = self.leaf

    def branch(self, parent, ident="live-branch"):
        self.entries.append(
            {
                "type": "message",
                "id": ident,
                "parentId": parent,
                "message": {"role": "user", "content": "Continue authorized work"},
            }
        )
        self.leaf = ident

    def call(self, key, arguments, response, failed=False):
        self.entries.extend(
            [
                {
                    "type": "message",
                    "id": key + "-call",
                    "parentId": self.leaf,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "toolCall", "id": key, "name": "todo", "arguments": arguments}
                        ],
                    },
                },
                {
                    "type": "message",
                    "id": key + "-result",
                    "parentId": key + "-call",
                    "message": {
                        "role": "toolResult",
                        "toolCallId": key,
                        "toolName": "todo",
                        "isError": failed,
                        "content": [{"type": "text", "text": response}],
                    },
                },
            ]
        )
        self.leaf = key + "-result"

    def test_off_branch_create_does_not_resurrect_goal(self):
        self.call(
            "abandoned",
            {"action": "create", "subject": "Do not replay"},
            "Created #2: Do not replay (pending)",
        )
        self.branch(self.fork_point)
        self.assertEqual([t["id"] for t in recovery.task_snapshot(self.entries)], [1])

    def test_off_branch_update_does_not_complete_live_goal(self):
        self.call(
            "abandoned",
            {"action": "update", "id": 1, "status": "completed", "addBlockedBy": [99]},
            "Updated #1",
        )
        self.branch(self.fork_point)
        task = recovery.task_snapshot(self.entries)[0]
        self.assertEqual(task["status"], "pending")
        self.assertNotIn(99, task.get("blockedBy", []))

    def test_off_branch_clear_does_not_erase_live_goal(self):
        self.call("abandoned", {"action": "clear"}, "Cleared tasks")
        self.branch(self.fork_point)
        self.assertEqual([t["id"] for t in recovery.task_snapshot(self.entries)], [1])

    def test_off_branch_delete_does_not_delete_live_goal(self):
        self.call("abandoned", {"action": "delete", "id": 1}, "Deleted #1")
        self.branch(self.fork_point)
        self.assertEqual(recovery.task_snapshot(self.entries)[0]["status"], "pending")

    def test_reused_task_number_belongs_to_active_branch(self):
        self.call("old2", {"action": "create", "subject": "Abandoned goal"}, "Created #2")
        self.call("old3", {"action": "create", "subject": "Ghost goal"}, "Created #3")
        self.branch(self.fork_point)
        self.call("new2", {"action": "create", "subject": "Current repair"}, "Created #2")
        tasks = recovery.task_snapshot(self.entries)
        self.assertEqual(
            [(t["id"], t["subject"]) for t in tasks], [(1, "Keep this goal"), (2, "Current repair")]
        )

    def test_active_clear_still_clears(self):
        self.call("clear", {"action": "clear"}, "Cleared tasks")
        self.assertEqual(recovery.task_snapshot(self.entries), [])

    def test_empty_new_root_has_no_old_tasks(self):
        self.branch(None)
        self.assertEqual(recovery.task_snapshot(self.entries), [])

    def test_result_without_call_on_active_branch_is_ignored(self):
        self.call("off", {"action": "update", "id": 1, "status": "completed"}, "Updated #1")
        self.branch(self.fork_point)
        self.entries.append(
            {
                "type": "message",
                "id": "unmatched",
                "parentId": self.leaf,
                "message": {
                    "role": "toolResult",
                    "toolCallId": "off",
                    "toolName": "todo",
                    "content": [{"type": "text", "text": "Updated #1"}],
                },
            }
        )
        self.assertEqual(recovery.task_snapshot(self.entries)[0]["status"], "pending")

    def test_header_only_has_no_tasks(self):
        self.assertEqual(recovery.task_snapshot(self.entries[:1]), [])

    def test_malformed_ancestry_fails_closed(self):
        for change in (
            "missing-parent",
            "missing-field",
            "cycle",
            "duplicate-id",
            "missing-id",
            "empty-parent",
        ):
            with self.subTest(change=change):
                entries = copy.deepcopy(self.entries)
                if change == "missing-parent":
                    entries[-1]["parentId"] = "unknown"
                elif change == "missing-field":
                    entries[-1].pop("parentId")
                elif change == "cycle":
                    entries[-1]["parentId"] = entries[-1]["id"]
                elif change == "duplicate-id":
                    entries.append(copy.deepcopy(entries[-1]))
                elif change == "missing-id":
                    entries[-1].pop("id")
                else:
                    entries[-1]["parentId"] = ""
                with self.assertRaises(ValueError):
                    recovery.task_snapshot(entries)

    def test_reconstruction_does_not_modify_journal_entries(self):
        self.call("off", {"action": "clear"}, "Cleared tasks")
        self.branch(self.fork_point)
        before = copy.deepcopy(self.entries)
        recovery.task_snapshot(self.entries)
        self.assertEqual(self.entries, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
