import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts.pi_recovery import foremen as f
from scripts.pi_recovery import maistro_pi_start as start


def proc(name, parent=0):
    return {"comm": name, "parent": parent, "state": "S", "start_ticks": "1"}


def pane(name="maistro", pid=100):
    return {"session": name, "session_id": "$7", "pane": "%9", "pid": pid, "dead": False}


class ForemenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.roles = {
            n: {
                "session_id": str(uuid.uuid4()),
                "provider": "test",
                "model": "test",
                "thinking": "medium",
            }
            for n in f.NAMES
        }
        self.cfg = {
            "version": 1,
            "enabled": False,
            "roles": self.roles,
            "operator_session_id": "operator",
        }
        f.recovery.save_json(self.root / "config.json", self.cfg)
        self.now = 2000000000

    def tearDown(self):
        self.temp.cleanup()

    def status(self, name="maistro", **values):
        f.recovery.save_json(
            self.root / name / "status.json",
            {"session_id": self.roles[name]["session_id"], **values},
        )

    def peers(self, name="maistro", status="idle"):
        return {self.roles[name]["session_id"]: {"status": status}}

    def own(self):
        f.recovery.save_json(
            self.root / "maistro/owner.json",
            {"session_id": self.roles["maistro"]["session_id"], "process": {"pid": 100}},
        )

    def test_strict_flags_reject_truthy_values(self):
        self.assertTrue(f.strict_true(True))
        for value in (False, 1, "true", {}, None):
            self.assertFalse(f.strict_true(value))

    def test_disabled_configuration_cannot_launch(self):
        with patch.object(f, "ensure_role") as ensure:
            with self.assertRaisesRegex(ValueError, "not armed"):
                f.main(["--root", str(self.root), "ensure"])
            ensure.assert_not_called()

    def test_duplicate_session_ids_rejected(self):
        self.cfg["roles"]["homie1"]["session_id"] = self.roles["maistro"]["session_id"]
        f.recovery.save_json(self.root / "config.json", self.cfg)
        with self.assertRaisesRegex(ValueError, "distinct"):
            f.load(self.root)

    def test_unknown_tmux_error_is_not_absence(self):
        result = subprocess.CompletedProcess([], 1, "", "permission denied")
        with (
            patch.object(f.subprocess, "run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "no action"),
        ):
            f.inventory()

    def test_missing_server_can_be_bootstrapped(self):
        result = subprocess.CompletedProcess([], 1, "", "no server running on /tmp/test/default")
        with patch.object(f.subprocess, "run", return_value=result):
            self.assertEqual(f.inventory(), [])

    def test_empty_pane_pid_is_rejected(self):
        result = subprocess.CompletedProcess([], 0, "maistro\t$7\t%9\t\t0\n", "")
        with (
            patch.object(f.subprocess, "run", return_value=result),
            self.assertRaisesRegex(ValueError, "Invalid tmux identity"),
        ):
            f.inventory()

    def test_shell_preserved_by_new_window(self):
        with patch.object(f, "run", return_value="%10\n") as command:
            result = f.ensure_role(
                "maistro", self.roles["maistro"], self.root, [pane()], {100: proc("bash")}, self.now
            )
        self.assertEqual(result["state"], "started_unverified")
        argv = command.call_args.args[0]
        self.assertEqual(argv[1:4], ["new-window", "-t", "$7:"])
        self.assertNotIn("kill-session", argv)
        self.assertNotIn("send-keys", argv)

    def test_missing_name_creates_exact_session_not_prefix_match(self):
        with patch.object(f, "run", return_value="%10\n") as command:
            f.ensure_role(
                "maistro",
                self.roles["maistro"],
                self.root,
                [pane("maistro-other")],
                {100: proc("bash")},
                self.now,
            )
        self.assertEqual(command.call_args.args[0][1:5], ["new-session", "-d", "-s", "maistro"])

    def test_live_owner_is_not_restarted(self):
        self.own()
        with (
            patch.object(f.recovery, "owner_alive", return_value=True),
            patch.object(f, "run") as command,
        ):
            result = f.ensure_role(
                "maistro", self.roles["maistro"], self.root, [pane()], {100: proc("pi")}, self.now
            )
        self.assertEqual(result["state"], "running")
        command.assert_not_called()

    def test_live_owner_outside_named_pane_blocks_duplicate(self):
        self.own()
        with (
            patch.object(f.recovery, "owner_alive", return_value=True),
            self.assertRaisesRegex(ValueError, "outside"),
        ):
            f.observe("maistro", self.roles["maistro"], self.root, [], {100: proc("pi")})

    def test_unregistered_pi_is_preserved(self):
        with self.assertRaisesRegex(ValueError, "unregistered"):
            f.observe("maistro", self.roles["maistro"], self.root, [pane()], {100: proc("pi")})

    def test_launch_budget_and_cooldown(self):
        f.reserve_attempt(self.root, "maistro", self.now)
        with self.assertRaisesRegex(ValueError, "budget/backoff"):
            f.reserve_attempt(self.root, "maistro", self.now + 1)
        f.reserve_attempt(self.root, "maistro", self.now + 901)
        f.reserve_attempt(self.root, "maistro", self.now + 1802)
        with self.assertRaisesRegex(ValueError, "budget/backoff"):
            f.reserve_attempt(self.root, "maistro", self.now + 2703)

    def test_ambiguous_creation_is_not_claimed_running(self):
        with (
            patch.object(f, "run", return_value=""),
            self.assertRaisesRegex(ValueError, "outcome unknown"),
        ):
            f.ensure_role("maistro", self.roles["maistro"], self.root, [], {}, self.now)
        self.assertEqual(
            len(f.read_optional(self.root / "maistro/launch-attempts.json")["times"]), 1
        )

    def test_busy_role_is_not_poked(self):
        with patch.object(f, "object_output") as send:
            row = f.poke(
                "maistro",
                self.roles["maistro"],
                self.root,
                self.peers(status="tool:bash"),
                self.now,
            )
        self.assertEqual(row["wake"], "busy_or_unknown")
        send.assert_not_called()

    def test_unknown_status_is_not_poked(self):
        row = f.poke("maistro", self.roles["maistro"], self.root, self.peers(status="?"), self.now)
        self.assertEqual(row["wake"], "busy_or_unknown")

    def test_unassigned_homie_costs_no_model_call(self):
        row = f.poke("homie1", self.roles["homie1"], self.root, self.peers("homie1"), self.now)
        self.assertEqual(row["wake"], "unassigned_idle")

    def test_assignment_requires_identity_authority_and_future_expiry(self):
        path = self.root / "homie1/assignment.json"
        good = {
            "session_id": self.roles["homie1"]["session_id"],
            "scope": "owned fix",
            "authority": "operator lane",
            "expires_at": "2100-01-01T00:00:00Z",
        }
        f.recovery.save_json(path, good)
        self.assertTrue(f.valid_assignment(self.root, "homie1", self.roles["homie1"], self.now))
        for updates in (
            {"session_id": "wrong"},
            {"authority": ""},
            {"expires_at": 999},
            {"expires_at": "2000-01-01T00:00:00Z"},
        ):
            f.recovery.save_json(path, {**good, **updates})
            self.assertFalse(
                f.valid_assignment(self.root, "homie1", self.roles["homie1"], self.now)
            )

    def test_blocked_role_does_not_get_repeated_work_commands(self):
        self.status(mode="blocked", blocked_reason="owner approval")
        row = f.poke("maistro", self.roles["maistro"], self.root, self.peers(), self.now)
        self.assertEqual(row["wake"], "blocked")

    def test_delivery_deduplicated_and_not_progress(self):
        with patch.object(
            f, "object_output", return_value={"ok": True, "delivered": True, "id": "receipt"}
        ) as send:
            first = f.poke("maistro", self.roles["maistro"], self.root, self.peers(), self.now)
            second = f.poke(
                "maistro", self.roles["maistro"], self.root, self.peers(), self.now + 60
            )
        self.assertEqual(first["wake"], "delivered")
        self.assertFalse(first["progress_verified"])
        self.assertEqual(second["wake"], "deduplicated")
        self.assertEqual(send.call_count, 1)
        self.assertIn(self.roles["maistro"]["session_id"], send.call_args.args[0])

    def test_failed_delivery_is_not_success_and_attempt_is_durable(self):
        with (
            patch.object(f, "object_output", return_value={"ok": True, "delivered": False}),
            self.assertRaisesRegex(ValueError, "did not confirm"),
        ):
            f.poke("maistro", self.roles["maistro"], self.root, self.peers(), self.now)
        self.assertEqual(
            f.read_optional(self.root / "maistro/last-wake.json")["delivery"], "unknown"
        )

    def test_malformed_json_is_rejected(self):
        with (
            patch.object(f, "run", return_value="not JSON"),
            self.assertRaisesRegex(ValueError, "invalid JSON"),
        ):
            f.object_output(["fake"])

    def test_stale_work_progress_escalates_without_restart(self):
        self.status(mode="working", last_progress_at="2020-01-01T00:00:00Z")
        attention = f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        assert attention is not None
        self.assertIn("stale", attention)
        report = {"roles": [{"role": "maistro", "attention": "stale"}]}
        with patch.object(f, "object_output", return_value={"ok": True, "delivered": True}) as send:
            f.escalate(self.root, self.cfg, {"operator": {"status": "idle"}}, report, self.now)
            f.escalate(self.root, self.cfg, {"operator": {"status": "idle"}}, report, self.now + 30)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(report["alert"], "rate_limited")

    def test_read_only_check_reports_missing_roles_as_incomplete(self):
        with (
            patch.object(f, "inventory", return_value=[]),
            patch.object(f.health, "processes", return_value={}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(f.main(["--root", str(self.root), "check"]), 2)
        self.assertFalse((self.root / "last-cycle.json").exists())

    @unittest.skipUnless(shutil.which(f.TMUX), "optional native tmux integration")
    def test_native_tmux_new_window_preserves_original_shell(self):
        socket = "foreman-preserve-" + uuid.uuid4().hex
        base = [f.TMUX, "-f", "/dev/null", "-L", socket]

        def native(*args):
            return subprocess.run(
                base + list(args), capture_output=True, text=True, timeout=10, check=True
            ).stdout

        def only_private(argv, **kwargs):
            self.assertEqual(argv[0], f.TMUX)
            return native(*argv[1:])

        try:
            native("new-session", "-d", "-s", "maistro", "/bin/bash", "--noprofile", "--norc")
            fields = (
                native("list-panes", "-a", "-F", "#{session_id}\t#{pane_id}\t#{pane_pid}")
                .strip()
                .split("\t")
            )
            original = pane(pid=int(fields[2]))
            original.update(session_id=fields[0], pane=fields[1])
            with (
                patch.object(f, "run", side_effect=only_private),
                patch.object(
                    f, "start_command", return_value=["/bin/bash", "--noprofile", "--norc"]
                ),
            ):
                result = f.ensure_role(
                    "maistro",
                    self.roles["maistro"],
                    self.root,
                    [original],
                    f.health.processes(),
                    self.now,
                )
            self.assertEqual(result["state"], "started_unverified")
            panes = native("list-panes", "-a", "-F", "#{pane_id}\t#{pane_pid}").splitlines()
            self.assertEqual(len(panes), 2)
            self.assertIn(fields[1] + "\t" + fields[2], panes)
        finally:
            subprocess.run([*base, "kill-server"], capture_output=True, timeout=10)


class NonAttachingPiTests(unittest.TestCase):
    def test_ensure_existing_managed_session_never_attaches(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"sessionId": "saved", "cwd": directory, "owner": None}

            def tmux(*args, **kwargs):
                return subprocess.CompletedProcess(
                    [], 0, "saved\n" if args[0] == "show-option" else "", ""
                )

            with (
                patch.object(start.sys, "argv", ["start", "--ensure", "--state-dir", directory]),
                patch.object(start.recovery, "load_config", return_value=cfg),
                patch.object(start, "tmux", side_effect=tmux) as calls,
                patch.object(start.subprocess, "call") as attach,
            ):
                self.assertEqual(start.main(), 0)
                attach.assert_not_called()
                self.assertFalse(any(c.args[0] == "new-session" for c in calls.call_args_list))

    def test_ensure_missing_session_creates_without_attach(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"sessionId": "saved", "cwd": directory, "owner": None}

            def tmux(*args, **kwargs):
                return subprocess.CompletedProcess([], 1 if args[0] == "has-session" else 0, "", "")

            with (
                patch.object(start.sys, "argv", ["start", "--ensure", "--state-dir", directory]),
                patch.object(start.recovery, "load_config", return_value=cfg),
                patch.object(start, "tmux", side_effect=tmux) as calls,
                patch.object(start.subprocess, "call") as attach,
            ):
                self.assertEqual(start.main(), 0)
                attach.assert_not_called()
                self.assertEqual(sum(c.args[0] == "new-session" for c in calls.call_args_list), 1)

    def test_ensure_does_not_replace_foreign_named_session(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = {"sessionId": "saved", "cwd": directory, "owner": None}
            result = subprocess.CompletedProcess([], 0, "foreign\n", "")
            with (
                patch.object(start.sys, "argv", ["start", "--ensure", "--state-dir", directory]),
                patch.object(start.recovery, "load_config", return_value=cfg),
                patch.object(start, "tmux", return_value=result),
                patch.object(start.subprocess, "call") as attach,
            ):
                with self.assertRaisesRegex(ValueError, "not ours"):
                    start.main()
                attach.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
