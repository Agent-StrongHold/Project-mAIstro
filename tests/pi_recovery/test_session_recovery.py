import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts.pi_recovery import maistro_pi_pane as pane
from scripts.pi_recovery import maistro_pi_resume as r
from scripts.pi_recovery.recovery_paths import NODE, TMUX, session_manager_path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/pi_recovery/cli.py"
NATIVE = session_manager_path()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-recovery-test-")
        self.root = Path(self.temp.name)
        self.state = self.root / "home/state"
        self.state.mkdir(parents=True)
        self.session = self.root / "home/session.jsonl"
        self.handoff = self.root / "home/RESUME.md"
        self.handoff.write_text("Recover before any action. No blind replay.\n")
        self.sid = "11111111-1111-4111-8111-111111111111"
        self.entries = [
            {"type": "session", "version": 3, "id": self.sid, "cwd": str(self.root)},
            {
                "type": "message",
                "id": "a1",
                "parentId": None,
                "timestamp": "2026-09-12T00:00:00Z",
                "message": {
                    "role": "user",
                    "content": "reboot sentinel: preserve this goal",
                    "timestamp": 1,
                },
            },
        ]
        self.append_tool(
            "create",
            {"action": "create", "subject": "Finish goal"},
            "Created #1: Finish goal (pending)",
        )
        self.append_tool(
            "update", {"action": "update", "id": 1, "status": "in_progress"}, "Updated #1"
        )
        self.write_session()
        self.config = {
            "version": 1,
            "sessionId": self.sid,
            "sessionFile": str(self.session),
            "cwd": str(self.root),
            "handoff": str(self.handoff),
            "provider": "test-provider",
            "model": "test-model",
            "owner": None,
            "autoResume": True,
        }
        r.save_json(self.state / "config.json", self.config)
        r.checkpoint(self.state, self.config)

    def tearDown(self):
        self.temp.cleanup()

    def append_tool(self, key, arguments, response, failed=False):
        previous = self.entries[-1].get("id")
        self.entries.append(
            {
                "type": "message",
                "id": key + "a",
                "parentId": previous,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "toolCall", "id": key, "name": "todo", "arguments": arguments}
                    ],
                },
            }
        )
        self.entries.append(
            {
                "type": "message",
                "id": key + "b",
                "parentId": key + "a",
                "message": {
                    "role": "toolResult",
                    "toolCallId": key,
                    "toolName": "todo",
                    "isError": failed,
                    "content": [{"type": "text", "text": response}],
                },
            }
        )

    def write_session(self):
        self.session.write_bytes(b"".join((json.dumps(e) + "\n").encode() for e in self.entries))

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "resume", "--state-dir", str(self.state), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_complete_checkpoint_and_confirmed_tasks(self):
        original = self.session.read_bytes()
        data, _, record = r.checked_backup(self.state, self.config)
        self.assertEqual(data, original)
        tasks = json.loads(Path(record["taskSnapshot"]).read_text())
        self.assertEqual([(x["id"], x["status"]) for x in tasks], [(1, "in_progress")])
        self.assertEqual(self.session.read_bytes(), original)
        self.assertEqual(Path(record["snapshot"]).stat().st_mode & 0o777, 0o600)

    def test_failed_or_unacknowledged_task_update_is_not_applied(self):
        self.append_tool(
            "failed", {"action": "update", "id": 1, "status": "completed"}, "error", True
        )
        self.entries.append(
            {
                "type": "message",
                "id": "pending-entry",
                "parentId": self.entries[-1]["id"],
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "id": "pending",
                            "name": "todo",
                            "arguments": {"action": "update", "id": 1, "status": "completed"},
                        }
                    ],
                },
            }
        )
        self.assertEqual(r.task_snapshot(self.entries)[0]["status"], "in_progress")

    def test_partial_tail_preserved_and_complete_prefix_backed_up(self):
        original = self.session.read_bytes()
        damaged = original + b'{"unfinished":'
        self.session.write_bytes(damaged)
        record = r.checkpoint(self.state, self.config)
        self.assertGreater(record["incompleteTailBytesSkipped"], 0)
        self.assertEqual(r.checked_backup(self.state, self.config)[0], original)
        self.assertEqual(self.session.read_bytes(), damaged)
        self.assertTrue(pane.prepare(self.state))
        self.assertEqual(self.session.read_bytes(), damaged)

    def test_corrupt_complete_line_does_not_replace_good_checkpoint(self):
        before = (self.state / "checkpoint.json").read_bytes()
        self.session.write_bytes(self.session.read_bytes() + b"not-json\n")
        with self.assertRaises(ValueError):
            r.checkpoint(self.state, self.config)
        self.assertEqual((self.state / "checkpoint.json").read_bytes(), before)

    def test_wrong_session_id_fails_closed(self):
        wrong = {**self.config, "sessionId": "wrong"}
        with self.assertRaisesRegex(ValueError, "ID mismatch"):
            r.checkpoint(self.state, wrong)

    def test_snapshot_checksum_catches_line_ending_tampering(self):
        record = r.load_json(self.state / "checkpoint.json")
        p = Path(record["snapshot"])
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(ValueError, "checksum"):
            r.checked_backup(self.state, self.config)

    def test_task_checksum_catches_tampering(self):
        record = r.load_json(self.state / "checkpoint.json")
        Path(record["taskSnapshot"]).write_text("[]\n")
        with self.assertRaisesRegex(ValueError, "Task snapshot checksum"):
            r.checked_backup(self.state, self.config)

    def test_branch_projection_upgrade_preserves_legacy_sidecar(self):
        record = r.load_json(self.state / "checkpoint.json")
        legacy = Path(record["snapshot"]).with_suffix(".tasks.json")
        legacy_data = b'[{"id":99,"subject":"old all-branches projection"}]\n'
        legacy.write_bytes(legacy_data)
        record.update(taskSnapshot=str(legacy), taskSha256=r.sha(legacy_data), taskCount=1)
        record.pop("taskProjection")
        r.save_json(self.state / "checkpoint.json", record)
        self.assertEqual(r.checked_backup(self.state, self.config)[2], record)
        updated = r.checkpoint(self.state, self.config)
        self.assertEqual(updated["taskProjection"], "active-branch-v1")
        self.assertNotEqual(updated["taskSnapshot"], str(legacy))
        self.assertEqual(legacy.read_bytes(), legacy_data)
        self.assertEqual(r.checked_backup(self.state, self.config)[2], updated)

    def test_unknown_task_projection_is_rejected(self):
        record = r.load_json(self.state / "checkpoint.json")
        record["taskProjection"] = "unknown"
        r.save_json(self.state / "checkpoint.json", record)
        with self.assertRaisesRegex(ValueError, "Unsupported task snapshot projection"):
            r.checked_backup(self.state, self.config)

    def test_invalid_ancestry_keeps_previous_checkpoint(self):
        before = (self.state / "checkpoint.json").read_bytes()
        artifacts = sorted(p.name for p in (self.state / "snapshots").iterdir())
        self.entries.append(
            {
                "type": "message",
                "id": "bad",
                "parentId": "missing-parent",
                "message": {"role": "user", "content": "do not guess ancestry"},
            }
        )
        self.write_session()
        original = self.session.read_bytes()
        with self.assertRaisesRegex(ValueError, "Invalid task lineage"):
            r.checkpoint(self.state, self.config)
        self.assertEqual((self.state / "checkpoint.json").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.state / "snapshots").iterdir()), artifacts)
        self.assertEqual(self.session.read_bytes(), original)

    def test_live_owner_blocks_duplicate_start(self):
        self.config["owner"] = r.process_identity(os.getpid())
        r.save_json(self.state / "config.json", self.config)
        result = self.cli("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate writer", result.stderr)

    def test_pid_reuse_and_new_boot_are_not_live_owner(self):
        owner = r.process_identity(os.getpid())
        assert owner is not None
        self.assertTrue(r.owner_alive(owner))
        self.assertFalse(r.owner_alive({**owner, "startTicks": "-1"}))
        self.assertFalse(r.owner_alive({**owner, "bootId": "previous-boot"}))

    def test_dry_run_pins_session_model_and_does_not_replay(self):
        result = self.cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertIn(str(self.session), plan["launchCommand"])
        self.assertIn("test-model", plan["launchCommand"])
        self.assertFalse(plan["automaticJobReplay"])
        self.assertIn("Continue the user", plan["launchCommand"][-1])

    def test_restore_check_survives_missing_original_without_mutation(self):
        self.session.unlink()
        before = (self.state / "config.json").read_bytes()
        result = self.cli("--check", "--recover-backup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.session.exists())
        self.assertFalse((self.state / "recovered").exists())
        self.assertEqual((self.state / "config.json").read_bytes(), before)

    def test_nonterminal_does_not_launch_pi(self):
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interactive terminal", result.stderr)

    def test_atomic_failure_keeps_previous_record(self):
        target = self.state / "atomic.json"
        r.save_json(target, {"old": True})
        before = target.read_bytes()
        with (
            patch.object(r.os, "replace", side_effect=OSError("simulated interrupted rename")),
            self.assertRaises(OSError),
        ):
            r.save_json(target, {"new": True})
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.state.glob(".writing-*")), [])

    def test_retention_only_prunes_owned_snapshots(self):
        unrelated = self.state / "snapshots/keep-me.txt"
        unrelated.write_text("do not delete")
        for n in range(5):
            self.entries.append(
                {
                    "type": "custom",
                    "id": str(n),
                    "parentId": self.entries[-1]["id"],
                    "data": {"generation": n},
                }
            )
            self.write_session()
            r.checkpoint(self.state, self.config)
        self.assertEqual(len(list((self.state / "snapshots").glob("*.jsonl"))), 3)
        self.assertTrue(unrelated.exists())
        self.assertTrue(self.session.exists())

    def test_second_recovery_lock_is_rejected(self):
        with (
            r.locked(self.state / "test.lock"),
            self.assertRaisesRegex(ValueError, "lock unavailable"),
            r.locked(self.state / "test.lock", nonblocking=True),
        ):
            self.fail("second lock entered")

    @unittest.skipUnless(
        NATIVE.is_file() and shutil.which(NODE), "optional offline Pi SDK + Node integration"
    )
    def test_cold_native_load_after_volatile_state_removed(self):
        volatile = self.root / "tmp"
        volatile.mkdir()
        (volatile / "running.json").write_text('{"state":"running"}')
        result = self.cli("--checkpoint")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        shutil.rmtree(volatile)
        self.session.unlink()
        code = (
            """
import {SessionManager} from '"""
            + NATIVE.as_uri()
            + """';
const sm=SessionManager.open(process.argv[1]);
const context=sm.buildSessionContext();
console.log(JSON.stringify({id:sm.getSessionId(),messages:context.messages.length,
  sentinel:JSON.stringify(context.messages).includes('reboot sentinel')}));
"""
        )
        restored = subprocess.run(
            [NODE, "--input-type=module", "-e", code, record["snapshot"]],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(restored.returncode, 0, restored.stderr)
        observed = json.loads(restored.stdout)
        self.assertEqual(observed["id"], self.sid)
        self.assertTrue(observed["sentinel"])
        self.assertGreater(observed["messages"], 0)
        self.assertEqual(r.checked_backup(self.state, self.config)[2]["taskCount"], 1)

    @unittest.skipUnless(shutil.which(TMUX), "optional native tmux integration")
    def test_real_tmux_isolated_server_create_tag_reattach_lookup(self):
        socket = "pi-recovery-test-" + uuid.uuid4().hex

        def run(*args):
            return subprocess.run(
                [TMUX, "-f", "/dev/null", "-L", socket, *args],
                capture_output=True,
                text=True,
                timeout=10,
            )

        try:
            self.assertEqual(run("new-session", "-d", "-s", "pi", "/bin/cat").returncode, 0)
            tagged = run("set-option", "-t", "pi", "@maistro_session_id", self.sid)
            self.assertEqual(tagged.returncode, 0, tagged.stderr)
            self.assertEqual(run("has-session", "-t", "=pi").returncode, 0)
            self.assertEqual(
                run("show-option", "-qv", "-t", "pi", "@maistro_session_id").stdout.strip(),
                self.sid,
            )
        finally:
            # This uniquely named test server contains only our dummy cat, never live Pi/team sessions.
            run("kill-server")


if __name__ == "__main__":
    unittest.main(verbosity=2)
