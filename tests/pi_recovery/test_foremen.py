import contextlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.pi_recovery import foremen as f
from scripts.pi_recovery import maistro_pi_start as start
from tests.pi_recovery.test_entrypoints import package_import_path


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
            "cwd": str(self.root),
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

    def test_failed_external_command_is_an_error_not_silence(self):
        result = subprocess.CompletedProcess([], 3, "", "boom")
        with (
            patch.object(f.subprocess, "run", return_value=result),
            self.assertRaisesRegex(RuntimeError, r"failed \(3\): boom"),
        ):
            f.run(["fake-tool"])

    def test_object_output_rejects_non_object_payloads(self):
        with (
            patch.object(f, "run", return_value="[]\n"),
            self.assertRaisesRegex(ValueError, "JSON object"),
        ):
            f.object_output(["fake"])

    def test_load_rejects_unusable_manifests(self):
        for text in ("[]", '{"version": 2}', '{"version": 1, "roles": {}}'):
            (self.root / "config.json").write_text(text)
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Incomplete"):
                f.load(self.root)

    def test_load_requires_explicit_role_fields(self):
        self.cfg["roles"]["maistro"]["thinking"] = ""
        f.recovery.save_json(self.root / "config.json", self.cfg)
        with self.assertRaisesRegex(ValueError, "provider/model/thinking"):
            f.load(self.root)

    def test_load_fails_closed_when_a_role_brief_is_missing(self):
        with (
            patch.object(f, "HERE", self.root / "empty"),
            self.assertRaisesRegex(ValueError, "Missing role brief"),
        ):
            f.load(self.root)

    def test_read_optional_rejects_non_object_state_files(self):
        (self.root / "maistro").mkdir()
        (self.root / "maistro/owner.json").write_text("[]\n")
        with self.assertRaisesRegex(ValueError, "Expected object"):
            f.read_optional(self.root / "maistro/owner.json")

    def test_inventory_parses_live_rows_exactly(self):
        stdout = "maistro\t$7\t%9\t123\t0\nhomie1\t$8\t%10\t456\t1\n"
        result = subprocess.CompletedProcess([], 0, stdout, "")
        with patch.object(f.subprocess, "run", return_value=result):
            rows = f.inventory()
        self.assertEqual(
            rows,
            [
                {
                    "session": "maistro",
                    "session_id": "$7",
                    "pane": "%9",
                    "pid": 123,
                    "dead": False,
                },
                {
                    "session": "homie1",
                    "session_id": "$8",
                    "pane": "%10",
                    "pid": 456,
                    "dead": True,
                },
            ],
        )

    def test_inventory_rejects_non_positive_pane_pids(self):
        result = subprocess.CompletedProcess([], 0, "maistro\t$7\t%9\t0\t0\n", "")
        with (
            patch.object(f.subprocess, "run", return_value=result),
            self.assertRaisesRegex(ValueError, "Invalid pane PID"),
        ):
            f.inventory()

    def test_live_owner_with_another_session_identity_is_preserved(self):
        self.own()
        record = f.read_optional(self.root / "maistro/owner.json")
        record["session_id"] = str(uuid.uuid4())
        f.recovery.save_json(self.root / "maistro/owner.json", record)
        with (
            patch.object(f.recovery, "owner_alive", return_value=True),
            self.assertRaisesRegex(ValueError, "another session identity"),
        ):
            f.observe("maistro", self.roles["maistro"], self.root, [pane()], {100: proc("pi")})

    def test_unknown_pane_process_is_preserved(self):
        with self.assertRaisesRegex(ValueError, "unknown pane process"):
            f.observe("maistro", self.roles["maistro"], self.root, [pane()], {})

    def test_progress_attention_is_none_without_status(self):
        self.assertIsNone(
            f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        )

    def test_status_identity_mismatch_needs_attention(self):
        self.status(session_id="other-identity")
        attention = f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        self.assertIn("identity mismatch", attention)

    def test_blocked_status_reports_its_reason(self):
        self.status(mode="blocked", blocked_reason="owner approval")
        attention = f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        self.assertIn("owner approval", attention)

    def test_non_working_modes_need_no_attention(self):
        self.status(mode="idle")
        self.assertIsNone(
            f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        )

    def test_naive_progress_timestamp_is_flagged(self):
        self.status(mode="working", last_progress_at="2020-01-01T00:00:00")
        attention = f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        self.assertIn("lacks timezone", attention)

    def test_missing_progress_timestamp_is_flagged(self):
        self.status(mode="working")
        attention = f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        self.assertIn("missing/invalid", attention)

    def test_future_progress_timestamp_is_flagged(self):
        self.status(mode="working", last_progress_at="2999-01-01T00:00:00Z")
        attention = f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        self.assertIn("future", attention)

    def test_fresh_progress_needs_no_attention(self):
        fresh = datetime.fromtimestamp(self.now - 60, tz=UTC).isoformat()
        self.status(mode="working", last_progress_at=fresh)
        self.assertIsNone(
            f.progress_attention(self.root, "maistro", self.roles["maistro"], self.now)
        )

    def test_assignment_with_unparseable_expiry_is_not_valid(self):
        path = self.root / "homie1/assignment.json"
        f.recovery.save_json(
            path,
            {
                "session_id": self.roles["homie1"]["session_id"],
                "scope": "owned fix",
                "authority": "operator lane",
                "expires_at": "not-a-timestamp",
            },
        )
        self.assertFalse(f.valid_assignment(self.root, "homie1", self.roles["homie1"], self.now))

    def test_roster_requires_confirmed_ok_and_a_session_list(self):
        for payload in ({"ok": "true", "sessions": []}, {"ok": True, "sessions": {}}, {"ok": True}):
            with (
                self.subTest(payload=payload),
                patch.object(f, "object_output", return_value=payload),
                self.assertRaisesRegex(ValueError, "roster unavailable"),
            ):
                f.roster()
        with patch.object(
            f, "object_output", return_value={"ok": True, "sessions": [{"id": "s1"}]}
        ):
            self.assertEqual(f.roster(), {"s1": {"id": "s1"}})

    def test_disconnected_peer_is_reported_not_poked(self):
        with patch.object(f, "object_output") as send:
            row = f.poke("maistro", self.roles["maistro"], self.root, {}, self.now)
        self.assertEqual(row["wake"], "not_connected")
        send.assert_not_called()

    def test_stale_status_identity_blocks_the_nudge(self):
        f.recovery.save_json(
            self.root / "maistro/status.json",
            {"session_id": "stale", "mode": "idle"},
        )
        with self.assertRaisesRegex(ValueError, "stale/mismatched"):
            f.poke("maistro", self.roles["maistro"], self.root, self.peers(), self.now)

    def test_launch_refuses_a_duplicate_while_the_pinned_owner_lives(self):
        self.own()
        with (
            patch.object(f.recovery, "owner_alive", return_value=True),
            self.assertRaisesRegex(ValueError, "refusing duplicate"),
        ):
            f.launch(self.root, "maistro", self.cfg)

    def test_launch_requires_the_foreman_own_tmux_pane(self):
        with (
            patch.object(f.recovery, "owner_alive", return_value=False),
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(ValueError, "their tmux pane"),
        ):
            f.launch(self.root, "maistro", self.cfg)

    def test_launch_refuses_an_ambiguous_window_identity(self):
        with (
            patch.object(f.recovery, "owner_alive", return_value=False),
            patch.dict(os.environ, {"TMUX_PANE": "%12"}),
            patch.object(f, "run", return_value="junk\n"),
            self.assertRaisesRegex(ValueError, "Cannot identify own window"),
        ):
            f.launch(self.root, "maistro", self.cfg)

    def test_launch_requires_ready_provider_credentials(self):
        with (
            patch.object(f.recovery, "owner_alive", return_value=False),
            patch.dict(os.environ, {"TMUX_PANE": "%12"}),
            patch.object(f, "run", side_effect=["@3\n", ""]),
            patch.object(f, "object_output", return_value={"status": "expired"}),
            self.assertRaisesRegex(ValueError, "credentials"),
        ):
            f.launch(self.root, "maistro", self.cfg)

    def test_launch_records_owner_exit_and_survives_a_keyboard_interrupt(self):
        child = Mock(pid=1234)
        child.wait.side_effect = [KeyboardInterrupt, 0]
        with (
            patch.object(f.recovery, "owner_alive", return_value=False),
            patch.dict(os.environ, {"TMUX_PANE": "%12"}),
            patch.object(f, "run", side_effect=["@3\n", ""]),
            patch.object(f, "object_output", return_value={"status": "ready"}),
            patch.object(f.recovery, "process_identity", return_value={"pid": 1234}),
            patch.object(f.subprocess, "Popen", return_value=child),
        ):
            self.assertEqual(f.launch(self.root, "maistro", self.cfg), 0)
        record = f.read_optional(self.root / "maistro/owner.json")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["pane"], "%12")

    def test_armed_launch_action_requires_a_role(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        with self.assertRaises(SystemExit):
            f.main(["--root", str(self.root), "launch"])

    def test_armed_launch_action_runs_only_the_named_role(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        with patch.object(f, "launch", return_value=7) as launch:
            self.assertEqual(f.main(["--root", str(self.root), "launch", "homie1"]), 7)
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[1], "homie1")

    def test_ensure_cycle_reconciles_under_lock_and_writes_history(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        panes = [pane("pi", pid=1), pane("maistro", pid=100)]
        table = {1: proc("bash"), 100: proc("pi")}
        with (
            patch.object(f, "inventory", return_value=panes),
            patch.object(f.health, "processes", return_value=table),
            patch.object(f, "roster", return_value={}) as roster,
            patch.object(
                f,
                "ensure_role",
                side_effect=[
                    {"role": "maistro", "state": "running"},
                    {"role": "homie1", "state": "running"},
                ],
            ) as ensure,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(f.main(["--root", str(self.root), "ensure"]), 0)
        roster.assert_called_once()
        self.assertEqual(ensure.call_count, 2)
        history = f.read_optional(self.root / "last-cycle.json")
        self.assertEqual([row["role"] for row in history["roles"]], ["maistro", "homie1"])

    def test_ensure_cycle_boots_a_missing_pi_session_before_reconciling(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        with (
            patch.object(f, "inventory", return_value=[]),
            patch.object(f.health, "processes", return_value={}),
            patch.object(f, "run", return_value="") as run,
            patch.object(f, "roster", return_value={}),
            patch.object(f, "ensure_role", return_value={"role": "x", "state": "needs_session"}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(f.main(["--root", str(self.root), "ensure"]), 0)
        self.assertIn("start", run.call_args.args[0])
        self.assertTrue((self.root / "last-cycle.json").exists())

    def test_cycle_nudges_only_connected_running_roles(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        peers = {
            self.roles["maistro"]["session_id"]: {"status": "idle"},
            self.roles["homie1"]["session_id"]: {"status": "idle"},
        }
        for name, pid in (("maistro", 100), ("homie1", 101)):
            f.recovery.save_json(
                self.root / name / "owner.json",
                {"session_id": self.roles[name]["session_id"], "process": {"pid": pid}},
            )
        panes = [pane("pi", pid=1), pane("maistro", pid=100), pane("homie1", pid=101)]
        table = {1: proc("bash"), 100: proc("pi"), 101: proc("pi")}
        with (
            patch.object(f, "inventory", return_value=panes),
            patch.object(f.health, "processes", return_value=table),
            patch.object(f.recovery, "owner_alive", return_value=True),
            patch.object(f, "roster", return_value=peers),
            patch.object(
                f,
                "ensure_role",
                side_effect=[
                    {"role": "maistro", "state": "running"},
                    {"role": "homie1", "state": "running"},
                ],
            ),
            patch.object(f, "object_output", return_value={"ok": True, "delivered": True}),
            contextlib.redirect_stdout(io.StringIO()) as shown,
        ):
            self.assertEqual(f.main(["--root", str(self.root), "cycle"]), 0)
        report = json.loads(shown.getvalue())
        wakes = {row["role"]: row.get("wake") for row in report["roles"]}
        self.assertEqual(wakes["maistro"], "delivered")
        self.assertEqual(wakes["homie1"], "unassigned_idle")
        self.assertEqual(report["roles"][0]["progress_verified"], False)

    def test_cycle_records_role_errors_without_abandoning_the_other(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        panes = [pane("pi", pid=1), pane("maistro", pid=100)]
        table = {1: proc("bash"), 100: proc("pi")}
        with (
            patch.object(f, "inventory", return_value=panes),
            patch.object(f.health, "processes", return_value=table),
            patch.object(f, "roster", return_value={}),
            patch.object(
                f,
                "ensure_role",
                side_effect=[{"role": "maistro", "state": "running"}, ValueError("boom")],
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(f.main(["--root", str(self.root), "ensure"]), 2)
        history = f.read_optional(self.root / "last-cycle.json")
        self.assertEqual(history["roles"][0]["state"], "running")
        self.assertIn("boom", history["roles"][1]["error"])

    def test_connected_role_outside_an_owned_pane_is_never_duplicated(self):
        self.cfg.update(enabled=True)
        f.recovery.save_json(self.root / "config.json", self.cfg)
        peers = {self.roles["maistro"]["session_id"]: {"status": "idle"}}
        panes = [pane("pi", pid=1)]
        table = {1: proc("bash")}
        with (
            patch.object(f, "inventory", return_value=panes),
            patch.object(f.health, "processes", return_value=table),
            patch.object(f, "roster", return_value=peers),
            patch.object(
                f,
                "ensure_role",
                side_effect=[{"role": "homie1", "state": "needs_session"}],
            ) as ensure,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(f.main(["--root", str(self.root), "ensure"]), 2)
        self.assertEqual(ensure.call_count, 1)
        history = f.read_optional(self.root / "last-cycle.json")
        self.assertIn("do not duplicate", history["roles"][0]["error"])

    def test_escalation_delivery_must_be_confirmed(self):
        report = {"roles": [{"role": "maistro", "attention": "stale"}]}
        with (
            patch.object(f, "object_output", return_value={"ok": True, "delivered": False}),
            self.assertRaisesRegex(ValueError, "not confirmed"),
        ):
            f.escalate(self.root, self.cfg, {"operator": {"status": "idle"}}, report, self.now)
        self.assertEqual(f.read_optional(self.root / "last-alert.json")["delivery"], "unknown")

    def test_no_problems_makes_no_alert(self):
        report = {"roles": [{"role": "maistro", "state": "running"}]}
        with patch.object(f, "object_output") as send:
            f.escalate(self.root, self.cfg, {"operator": {"status": "idle"}}, report, self.now)
        send.assert_not_called()
        self.assertNotIn("alert", report)

    def test_cli_entrypoint_reports_failures_as_error_json(self):
        with (
            package_import_path(),
            patch.object(sys, "argv", ["foremen", "--root", str(self.root / "absent"), "check"]),
            patch.object(sys, "stderr", new=io.StringIO()) as errors,
            self.assertRaises(SystemExit) as exited,
        ):
            runpy.run_module("pi_recovery.foremen", run_name="__main__", alter_sys=True)
        self.assertEqual(exited.exception.code, 2)
        payload = json.loads(errors.getvalue())
        self.assertIn("Cannot read recovery metadata", payload["error"])
        self.assertIs(payload["progress_verified"], False)


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
