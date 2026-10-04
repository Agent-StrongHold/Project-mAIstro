"""Portable bindings/entrypoint regressions; no agents, services or network."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import scripts.pi_recovery.configure as configure
from scripts.pi_recovery import foremen as f
from scripts.pi_recovery import maistro_pi_resume as r
from scripts.pi_recovery import recovery_paths

SOURCE = Path(__file__).resolve().parents[2] / "scripts/pi_recovery"


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "private state"
        self.cwd = self.base / "work space"
        self.cwd.mkdir()
        self.args = [
            "--root",
            str(self.root),
            "--cwd",
            str(self.cwd),
            "--operator-session-id",
            "operator-example",
            "--provider",
            "fixture-provider",
            "--model",
            "fixture-model",
        ]

    def tearDown(self):
        self.temp.cleanup()

    def configure(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(configure.main(self.args), 0)
        return f.load(self.root)

    def test_fresh_bindings_are_disabled_private_and_distinct(self):
        cfg = self.configure()
        self.assertIs(cfg["enabled"], False)
        self.assertEqual(cfg["cwd"], str(self.cwd))
        self.assertEqual(cfg["operator_session_id"], "operator-example")
        ids = [role["session_id"] for role in cfg["roles"].values()]
        self.assertEqual(len(set(ids)), 2)
        for sid in ids:
            self.assertEqual(str(uuid.UUID(sid)), sid)
        self.assertEqual((self.root / "config.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["config.json"])

    def test_configure_never_replaces_existing_bindings(self):
        self.configure()
        before = (self.root / "config.json").read_bytes()
        with self.assertRaises(FileExistsError):
            configure.main(self.args)
        self.assertEqual((self.root / "config.json").read_bytes(), before)

    def test_configure_rejects_relative_or_missing_workspace(self):
        for cwd in ("relative", str(self.base / "missing")):
            with self.subTest(cwd=cwd), self.assertRaisesRegex(ValueError, "absolute directory"):
                configure.main([*self.args, "--cwd", cwd])
        self.assertFalse(self.root.exists())

    def test_invalid_workspace_blocks_an_armed_cycle_before_tools(self):
        cfg = self.configure()
        cfg.update(enabled=True, cwd="relative")
        r.save_json(self.root / "config.json", cfg)
        with (
            patch.object(f, "inventory") as inventory,
            self.assertRaisesRegex(ValueError, "absolute directory"),
        ):
            f.main(["--root", str(self.root), "cycle"])
        inventory.assert_not_called()

    def test_default_handoff_is_private_state_not_a_host_recovery_tree(self):
        self.assertEqual(r.DEFAULT_HANDOFF, r.DEFAULT_STATE / "RESUME.md")

    def test_foreman_command_carries_explicit_root_across_tmux(self):
        argv = f.start_command(self.root, "homie1")
        self.assertIn("PI_FOREMEN_ROOT=" + str(self.root), argv)
        self.assertIn("PI_RECOVERY_PI=" + recovery_paths.PI, argv)
        self.assertIn("PI_FOREMEN_INTERCOM_CLI=" + str(recovery_paths.INTERCOM_CLI), argv)

    def test_bound_command_does_not_copy_arbitrary_environment(self):
        with patch.dict(os.environ, {"UNRELATED_PRIVATE_VALUE": "do-not-forward"}):
            argv = recovery_paths.bound_command(
                [sys.executable, "-c", "pass"], PI_RECOVERY_STATE_DIR=str(self.root)
            )
        self.assertIn("PI_RECOVERY_STATE_DIR=" + str(self.root), argv)
        self.assertFalse(
            any("UNRELATED_PRIVATE_VALUE" in value or "do-not-forward" in value for value in argv)
        )

    def test_new_terminal_uses_admitted_workspace(self):
        cfg = self.configure()
        role = cfg["roles"]["maistro"]
        with patch.object(f, "run", return_value="%12\n") as run:
            f.ensure_role("maistro", role, self.root, [], {}, 2000000000, cwd=cfg["cwd"])
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("-c") + 1], str(self.cwd))
        self.assertIn("cli.py", argv[-1])
        self.assertNotIn("send-keys", argv)

    def test_pi_child_uses_manifest_workspace_and_not_parent_identity(self):
        cfg = self.configure()
        child = Mock(pid=1234)
        child.wait.return_value = 0
        with (
            patch.dict(
                os.environ, {"TMUX_PANE": "%12", "PI_SESSION_ID": "old", "PI_SESSION_FILE": "old"}
            ),
            patch.object(f, "run", return_value="@3\n"),
            patch.object(f, "object_output", return_value={"status": "ready"}),
            patch.object(f.recovery, "owner_alive", return_value=False),
            patch.object(f.recovery, "process_identity", return_value={"pid": 1234}),
            patch.object(f.subprocess, "Popen", return_value=child) as launch,
        ):
            self.assertEqual(f.launch(self.root, "maistro", cfg), 0)
        self.assertEqual(launch.call_args.kwargs["cwd"], str(self.cwd))
        self.assertNotIn("PI_SESSION_ID", launch.call_args.kwargs["env"])
        self.assertNotIn("PI_SESSION_FILE", launch.call_args.kwargs["env"])
        self.assertIn(cfg["roles"]["maistro"]["session_id"], launch.call_args.args[0])

    def test_intercom_uses_manifest_workspace(self):
        cfg = self.configure()
        role = cfg["roles"]["maistro"]
        peers = {role["session_id"]: {"status": "idle"}}
        with patch.object(f, "object_output", return_value={"ok": True, "delivered": True}) as send:
            f.poke("maistro", role, self.root, peers, 2000000000, cwd=cfg["cwd"])
        self.assertEqual(send.call_args.kwargs["cwd"], str(self.cwd))

    def test_relocated_package_configures_without_repository_or_agent(self):
        installed = self.base / "installation with spaces" / "pi_recovery"
        shutil.copytree(SOURCE, installed, ignore=shutil.ignore_patterns("__pycache__"))
        result = subprocess.run(
            [sys.executable, str(installed / "cli.py"), "configure", *self.args],
            cwd=self.base,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["agents_started"], 0)
        help_result = subprocess.run(
            [sys.executable, str(installed / "cli.py"), "resume", "--help"],
            cwd=self.base,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--recover-backup", help_result.stdout)

    def test_runtime_sources_do_not_embed_a_user_home(self):
        for path in SOURCE.glob("*.py"):
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(r"/home/[^/\s]+/", path.read_text()))


if __name__ == "__main__":
    unittest.main()
