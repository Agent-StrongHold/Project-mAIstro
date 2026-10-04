import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts.pi_recovery import check_foremen as f


def proc(name, parent=0, state="S"):
    return {"comm": name, "parent": parent, "state": state, "start_ticks": "1"}


def pane(name="pi", pid=100, dead=False, handle="%1"):
    return {"session": name, "pane": handle, "pid": pid, "dead": dead}


class ForemanChecks(unittest.TestCase):
    def test_shell_is_not_pi(self):
        row = f.assess([pane()], {100: proc("bash")})[0]
        self.assertEqual(row["state"], "no_pi_process")

    def test_python_wrapper_with_pi_child_is_live(self):
        row = f.assess([pane()], {100: proc("python3"), 101: proc("pi", 100)})[0]
        self.assertEqual(row["state"], "pi_present")
        self.assertEqual(row["pi_pids"], [101])

    def test_similar_session_name_does_not_match(self):
        rows = f.assess([pane("pi-other")], {100: proc("pi")})
        self.assertEqual(rows[0]["state"], "missing_session")

    def test_dead_pane_is_preserved_even_with_reused_pid(self):
        rows = f.assess([pane(dead=True)], {100: proc("pi")})
        self.assertEqual(rows[0]["state"], "dead_panes_preserved")
        self.assertEqual(rows[0]["pi_pids"], [])

    def test_missing_proc_is_unknown_not_dead(self):
        self.assertEqual(f.assess([pane()], {})[0]["state"], "unknown_process_identity")

    def test_zombie_pi_does_not_count(self):
        self.assertEqual(
            f.assess([pane()], {100: proc("pi", state="Z")})[0]["state"], "no_pi_process"
        )

    def test_all_panes_are_checked_without_discarding_shells(self):
        panes = [pane(), pane(pid=101, handle="%2")]
        rows = f.assess(panes, {100: proc("bash"), 101: proc("pi")})
        self.assertEqual(rows[0]["state"], "pi_present")
        self.assertEqual(rows[0]["panes"], ["%1", "%2"])

    def test_multiple_pi_is_reported_not_fixed(self):
        table = {100: proc("bash"), 101: proc("pi", 100), 102: proc("pi", 100)}
        self.assertEqual(f.assess([pane()], table)[0]["state"], "multiple_pi_processes")

    def test_inventory_error_is_not_absence(self):
        with patch.object(
            f.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", "server unavailable"),
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "inventory unavailable"):
                f.tmux_panes()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][1:4], ["list-panes", "-a", "-F"])

    def test_empty_pid_is_rejected_before_assessment(self):
        result = subprocess.CompletedProcess([], 0, "pi\t%1\t\t0\n", "")
        with (
            patch.object(f.subprocess, "run", return_value=result),
            self.assertRaisesRegex(ValueError, "pane identity"),
        ):
            f.tmux_panes()

    def test_malformed_inventory_is_rejected(self):
        result = subprocess.CompletedProcess([], 0, "pi %1 100 0\n", "")
        with (
            patch.object(f.subprocess, "run", return_value=result),
            self.assertRaisesRegex(ValueError, "pane inventory"),
        ):
            f.tmux_panes()

    def test_proc_parser_handles_parentheses_in_name(self):
        with tempfile.TemporaryDirectory() as directory:
            pid = Path(directory) / "100"
            pid.mkdir()
            fields = ["S", "9"] + ["0"] * 17 + ["42"]
            (pid / "stat").write_text("100 (name (paren)) " + " ".join(fields))
            self.assertEqual(
                f.processes(Path(directory))[100],
                {"comm": "name (paren)", "state": "S", "parent": 9, "start_ticks": "42"},
            )

    def test_read_failure_never_becomes_healthy(self):
        out = io.StringIO()
        with (
            patch.object(f, "tmux_panes", side_effect=RuntimeError("failed lookup")),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(f.main([]), 2)
        report = json.loads(out.getvalue())
        self.assertIn("failed lookup", report["error"])
        self.assertEqual(report["mutations"], [])

    def test_process_presence_is_not_wake_or_progress_success(self):
        out = io.StringIO()
        panes = [pane(name, i + 100) for i, name in enumerate(f.NAMES)]
        table = {i + 100: proc("pi") for i in range(3)}
        with (
            patch.object(f, "tmux_panes", return_value=panes),
            patch.object(f, "processes", return_value=table),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(f.main(["--check"]), 2)
        report = json.loads(out.getvalue())
        self.assertTrue(report["all_named_pi_present"])
        self.assertFalse(report["wake_armed"])
        self.assertFalse(report["progress_verified"])
        self.assertEqual(report["mutations"], [])

    @unittest.skipUnless(shutil.which(f.TMUX), "optional native tmux integration")
    def test_native_tmux_preserves_shell_and_uses_exact_names(self):
        socket = "foremen-check-test-" + uuid.uuid4().hex

        def tmux(*args):
            return subprocess.run(
                [f.TMUX, "-f", "/dev/null", "-L", socket, *args],
                capture_output=True,
                text=True,
                timeout=10,
            )

        try:
            # Dummy shells only; no agent, network, or shared tmux server.
            for name in ("pi", "maistro", "homie1-other"):
                result = tmux("new-session", "-d", "-s", name, "/bin/bash", "--noprofile", "--norc")
                self.assertEqual(result.returncode, 0, result.stderr)
            before = f.tmux_panes(socket=socket)
            rows = f.assess(before, f.processes())
            self.assertEqual(
                [r["state"] for r in rows], ["no_pi_process", "no_pi_process", "missing_session"]
            )
            # Some tmux releases return success with an EMPTY PID here.
            # Do not require the upstream quirk; our observer uses enumeration.
            lookup = tmux("display-message", "-p", "-t", "=pi", "#{pane_pid}")
            actual = next(p["pid"] for p in before if p["session"] == "pi")
            self.assertIn(lookup.stdout.strip(), ("", str(actual)))
            self.assertEqual(before, f.tmux_panes(socket=socket))
        finally:
            # Only this test's unique server and its dummy shells.
            tmux("kill-server")


if __name__ == "__main__":
    unittest.main(verbosity=2)
