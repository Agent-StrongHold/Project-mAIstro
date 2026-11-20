"""Entrypoint dispatch, pane restore and start-mode regressions; fully offline.

No agents, services, tmux servers or network are started: every external effect
is patched, and every launched-process assertion is negative (attach/wait-for is
observed, never performed).
"""

import contextlib
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.pi_recovery import cli
from scripts.pi_recovery import maistro_pi_pane as pane
from scripts.pi_recovery import maistro_pi_resume as r
from scripts.pi_recovery import maistro_pi_start as start
from scripts.pi_recovery.recovery_paths import TMUX

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


@contextlib.contextmanager
def package_import_path():
    """Make the shipped package importable as ``pi_recovery`` for runpy.

    cli.py itself performs exactly this insertion at dispatch time; scoping it
    here keeps collection-order out of the test's meaning.
    """

    added = str(SCRIPTS) not in sys.path
    if added:
        sys.path.insert(0, str(SCRIPTS))
    try:
        yield
    finally:
        if added:
            sys.path.remove(str(SCRIPTS))


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class CliDispatchTests(unittest.TestCase):
    MODULE = "pi_recovery.check_foremen"

    def test_dispatch_imports_only_the_reviewed_package_module(self):
        tool = Mock()
        tool.main.return_value = 0
        with (
            package_import_path(),
            patch("importlib.import_module", return_value=tool) as resolve,
            patch.object(sys, "argv", ["cli.py", "observe", "--check"]),
            self.assertRaises(SystemExit) as exited,
        ):
            runpy.run_path(str(SCRIPTS / "pi_recovery" / "cli.py"), run_name="__main__")
        self.assertEqual(exited.exception.code, 0)
        resolve.assert_called_once_with(self.MODULE)
        tool.main.assert_called_once_with(["--check"])
        self.assertEqual(sys.path[0], str(SCRIPTS))

    def test_dispatch_reports_tool_failure_as_progress_unverified_json(self):
        tool = Mock()
        tool.main.side_effect = RuntimeError("tmux inventory unavailable")
        with (
            package_import_path(),
            patch("importlib.import_module", return_value=tool),
            patch.object(sys, "argv", ["cli.py", "observe"]),
            patch.object(sys, "stderr", new=io.StringIO()) as errors,
            self.assertRaises(SystemExit) as exited,
        ):
            runpy.run_path(str(SCRIPTS / "pi_recovery" / "cli.py"), run_name="__main__")
        self.assertEqual(exited.exception.code, 2)
        payload = json.loads(errors.getvalue())
        self.assertIn("tmux inventory unavailable", payload["error"])
        self.assertIs(payload["progress_verified"], False)

    def test_dispatch_reaches_real_tool_modules(self):
        # configure without its required options fails inside the real tool, and
        # pane's parser answers --help: dispatch resolves real package modules.
        with self.assertRaises(SystemExit):
            cli.main(["configure"])
        with self.assertRaises(SystemExit) as exited:
            cli.main(["pane", "--help"])
        self.assertEqual(exited.exception.code, 0)


class PaneRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-pane-test-")
        self.root = Path(self.temp.name)
        self.state = self.root / "home" / "state"
        self.state.mkdir(parents=True)
        self.session = self.root / "home" / "session.jsonl"
        self.handoff = self.root / "home" / "RESUME.md"
        self.handoff.write_text("Recover before any action. No blind replay.\n")
        self.sid = "11111111-1111-4111-8111-111111111111"
        self.session.write_text(
            json.dumps({"type": "session", "version": 3, "id": self.sid, "cwd": str(self.root)})
            + "\n"
        )
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

    def test_intact_journal_needs_no_checkpoint(self):
        self.assertFalse(pane.prepare(self.state))
        self.assertFalse((self.state / "last-recovery.json").exists())

    def test_missing_journal_restores_a_verified_checkpoint_into_a_new_file(self):
        self.session.unlink()
        with contextlib.redirect_stdout(io.StringIO()) as shown:
            self.assertTrue(pane.prepare(self.state))
        self.assertIn("Original preserved", shown.getvalue())
        record = r.load_json(self.state / "last-recovery.json")
        self.assertEqual(record["originalPreserved"], str(self.session))
        self.assertIs(record["automaticJobReplay"], False)
        self.assertTrue(record["checkpointSha256"])

    def test_corrupt_journal_is_replaced_by_checkpoint_but_kept_as_original(self):
        self.session.write_bytes(b"{not json at all}\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(pane.prepare(self.state))
        self.assertEqual(
            r.load_json(self.state / "last-recovery.json")["originalPreserved"], str(self.session)
        )

    def test_session_identity_mismatch_aborts_before_any_restore(self):
        config = r.load_json(self.state / "config.json")
        config["sessionId"] = "22222222-2222-4222-8222-222222222222"
        r.save_json(self.state / "config.json", config)
        with self.assertRaisesRegex(ValueError, "Session ID mismatch"):
            pane.prepare(self.state)
        self.assertFalse((self.state / "last-recovery.json").exists())

    def test_main_resumes_and_signals_the_boot_channel(self):
        with (
            patch.object(pane.recovery, "main", return_value=0) as resume,
            patch.object(pane.subprocess, "run") as signal,
        ):
            self.assertEqual(pane.main([str(self.state), "boot-chan"]), 0)
        self.assertEqual(resume.call_args.args[0], ["--state-dir", str(self.state)])
        self.assertEqual(signal.call_args.args[0], [TMUX, "wait-for", "-S", "boot-chan"])

    def test_main_adds_explicit_recover_backup_after_an_unreadable_journal(self):
        self.session.unlink()
        with (
            patch.object(pane.recovery, "main", return_value=0) as resume,
            patch.object(pane.subprocess, "run"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(pane.main([str(self.state), "boot-chan"]), 0)
        self.assertEqual(
            resume.call_args.args[0], ["--state-dir", str(self.state), "--recover-backup"]
        )

    def test_main_reports_resume_failure_but_still_signals_the_channel(self):
        with (
            patch.object(
                pane.recovery,
                "main",
                side_effect=ValueError("Resume requires an interactive terminal"),
            ),
            patch.object(pane.subprocess, "run") as signal,
            patch.object(sys, "stderr", new=io.StringIO()) as errors,
        ):
            self.assertEqual(pane.main([str(self.state), "boot-chan"]), 1)
        self.assertIn("Pi recovery failed", errors.getvalue())
        self.assertEqual(signal.call_args.args[0], [TMUX, "wait-for", "-S", "boot-chan"])


class StartModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-start-test-")
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir(parents=True)
        self.handoff = Path(self.temp.name) / "RESUME.md"
        self.handoff.write_text("Recover before any action. No blind replay.\n")
        self.sid = "33333333-3333-4333-8333-333333333333"
        r.save_json(
            self.state / "config.json",
            {
                "version": 1,
                "sessionId": self.sid,
                "sessionFile": str(self.state / "session.jsonl"),
                "cwd": str(self.state),
                "handoff": str(self.handoff),
                "provider": "test-provider",
                "model": "test-model",
                "owner": None,
                "autoResume": False,
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_check_mode_prints_the_plan_and_never_touches_a_server(self):
        with (
            patch.object(start.subprocess, "run", return_value=completed(1)) as shelled,
            patch.object(start.subprocess, "call") as attach,
            contextlib.redirect_stdout(io.StringIO()) as shown,
        ):
            self.assertEqual(start.main(["--check", "--state-dir", str(self.state)]), 0)
        plan = json.loads(shown.getvalue())
        self.assertEqual(plan["tmux"], "pi")
        self.assertFalse(plan["exists"])
        self.assertFalse(plan["ownerAlive"])
        self.assertEqual(plan["sessionId"], self.sid)
        self.assertIn("new-session", plan["wouldCreate"])
        attach.assert_not_called()
        self.assertEqual(shelled.call_args.args[0][:3], [TMUX, "has-session", "-t"])

    def managed_session(self):
        def tmux(*args, **kwargs):
            return completed(0, self.sid + "\n" if args[0] == "show-option" else "")

        return tmux

    def test_boot_mode_waits_for_the_session_exit_event_without_starting_pi(self):
        with (
            patch.object(start, "tmux", side_effect=self.managed_session()),
            patch.object(start.subprocess, "call", return_value=0) as waited,
        ):
            self.assertEqual(start.main(["--boot", "--state-dir", str(self.state)]), 0)
        self.assertEqual(
            waited.call_args.args[0], [TMUX, "wait-for", "maistro-pi-exit-" + self.sid]
        )

    def test_ensure_still_returns_before_any_attach_or_wait(self):
        with (
            patch.object(start, "tmux", side_effect=self.managed_session()),
            patch.object(start.subprocess, "call", return_value=0) as waited,
        ):
            self.assertEqual(start.main(["--ensure", "--state-dir", str(self.state)]), 0)
        waited.assert_not_called()

    def test_no_tmux_environment_attaches_the_exact_managed_session(self):
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        with (
            patch.object(start, "tmux", side_effect=self.managed_session()),
            patch.dict(os.environ, env, clear=True),
            patch.object(start.subprocess, "call", return_value=0) as attach,
        ):
            self.assertEqual(start.main(["--state-dir", str(self.state)]), 0)
        self.assertEqual(attach.call_args.args[0], [TMUX, "attach-session", "-t", "=pi"])

    def test_nested_tmux_client_switches_instead_of_attaching(self):
        with (
            patch.object(start, "tmux", side_effect=self.managed_session()),
            patch.dict(os.environ, {"TMUX": "%5"}),
            patch.object(start.subprocess, "call", return_value=0) as attach,
        ):
            self.assertEqual(start.main(["--state-dir", str(self.state)]), 0)
        self.assertEqual(attach.call_args.args[0], [TMUX, "switch-client", "-t", "=pi"])

    def test_original_pi_running_outside_tmux_blocks_a_duplicate(self):
        def tmux(*args, **kwargs):
            return completed(1 if args[0] == "has-session" else 0)

        with (
            patch.object(start, "tmux", side_effect=tmux),
            patch.object(start.recovery, "owner_alive", return_value=True),
            self.assertRaisesRegex(ValueError, "Original Pi still running"),
        ):
            start.main(["--state-dir", str(self.state)])

    def test_cli_entrypoint_succeeds_and_reports_failures(self):
        argv = ["start", "--check", "--state-dir", str(self.state)]
        with (
            package_import_path(),
            patch.object(start.subprocess, "run", return_value=completed(1)),
            patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as exited,
        ):
            runpy.run_module("pi_recovery.maistro_pi_start", run_name="__main__", alter_sys=True)
        self.assertEqual(exited.exception.code, 0)

        with (
            package_import_path(),
            patch.object(sys, "argv", ["start", "--state-dir", str(self.state / "absent")]),
            patch.object(sys, "stderr", new=io.StringIO()) as errors,
            self.assertRaises(SystemExit) as failed,
        ):
            runpy.run_module("pi_recovery.maistro_pi_start", run_name="__main__", alter_sys=True)
        self.assertEqual(failed.exception.code, 1)
        self.assertIn("maistro-pi-start", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
