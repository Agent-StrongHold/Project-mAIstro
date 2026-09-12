"""Tests for the "did the gates actually run" check (#262 AC-2).

The script's job is to tell apart states that can all render as "not green": a
check that ran and failed (someone else's problem), one that is still running
(nobody's problem yet), one that never ran at all, and one whose run record
exists but whose conclusion proves the enforcement did not execute to a verdict.
Absent/unfinished evidence is pending under the strict publisher contract;
non-executed evidence is a hard finding.

The other half of the job is refusing to answer when it cannot. A gate that
reports green on a payload it could not parse is worse than no gate, because it
converts "we do not know" into "we checked".
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-gates-ran.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_gates_ran", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(name: str, *, status: str = "completed", conclusion: str | None = "success") -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


def _payload(tmp_path: Path, runs: list[dict]) -> Path:
    path = tmp_path / "check-runs.json"
    path.write_text(json.dumps({"check_runs": runs}), encoding="utf-8")
    return path


def _envelope(tmp_path: Path, payload: dict | list) -> Path:
    path = tmp_path / "changed-files.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestTheThreeStates:
    def test_a_check_that_ran_and_passed_is_fine(self, check):
        v = check.evaluate(["a"], [_run("a")], require_complete=True)
        assert v.ok and v.ran == ["a"]

    def test_a_check_that_ran_and_failed_is_fine_here(self, check):
        """Someone else's gate reports that. This one asks only whether it ran —
        double-reporting a failure would make the two indistinguishable."""
        v = check.evaluate(["a"], [_run("a", conclusion="failure")], require_complete=True)
        assert v.ok

    def test_a_check_with_no_run_is_the_finding(self, check):
        """AC-2. The state that renders as an empty space rather than a red one."""
        v = check.evaluate(["a", "b"], [_run("a")], require_complete=True)
        assert v.absent == ["b"] and v.pending and not v.ok

    def test_action_required_is_the_finding_it_was_written_for(self, check):
        """The exact symptom of a push made with the default GITHUB_TOKEN: a run
        exists, so it looks checked, and it will never execute."""
        v = check.evaluate(
            ["a"],
            [_run("a", status="completed", conclusion="action_required")],
            require_complete=True,
        )
        assert v.not_executed == ["a"] and not v.pending and not v.ok

    def test_stale_is_treated_as_non_execution_evidence(self, check):
        v = check.evaluate(["a"], [_run("a", conclusion="stale")], require_complete=True)
        assert v.not_executed == ["a"] and not v.ok

    def test_skipped_required_check_is_not_execution_evidence(self, check):
        """A skipped check exists, but its enforcement body did not run."""
        v = check.evaluate(["a"], [_run("a", conclusion="skipped")], require_complete=True)
        assert v.not_executed == ["a"] and not v.ok

    def test_cancelled_required_check_is_not_execution_evidence(self, check):
        """Cancellation cannot certify that enforcement completed to a verdict."""
        v = check.evaluate(["a"], [_run("a", conclusion="cancelled")], require_complete=True)
        assert v.not_executed == ["a"] and not v.ok

    def test_in_progress_is_not_a_finding_without_require_complete(self, check):
        """It ran. That is the question this gate asks by default."""
        v = check.evaluate(
            ["a"], [_run("a", status="in_progress", conclusion=None)], require_complete=False
        )
        assert v.ok

    def test_in_progress_is_pending_with_require_complete(self, check):
        """The workflow publisher must wait rather than ejecting a healthy queue
        candidate simply because this check has not finished yet."""
        v = check.evaluate(
            ["a"], [_run("a", status="in_progress", conclusion=None)], require_complete=True
        )
        assert v.unfinished == ["a"] and v.pending and not v.ok

    def test_a_rerun_is_judged_by_its_latest_attempt(self, check):
        """GitHub keeps every attempt. Judging the first would report a check as
        non-executed forever after someone approved and re-ran it."""
        runs = [_run("a", conclusion="action_required"), _run("a", conclusion="success")]
        assert check.evaluate(["a"], runs, require_complete=True).ok

    def test_a_cancelled_duplicate_never_shadows_a_sibling_that_executed(self, check):
        """#1229: quality.yml/security.yml share one concurrency group across a
        `push` and a `pull_request` event for the same commit, so the loser of
        that race reports `cancelled` under the same check name a genuine
        completed sibling run also used. Whichever the check-runs API happens
        to return last must not decide the verdict -- the executed run always
        wins over the cancelled one, in either order."""
        executed_first = [_run("a", conclusion="success"), _run("a", conclusion="cancelled")]
        cancelled_first = [_run("a", conclusion="cancelled"), _run("a", conclusion="success")]
        assert check.evaluate(["a"], executed_first, require_complete=True).ok
        assert check.evaluate(["a"], cancelled_first, require_complete=True).ok

    def test_two_non_executed_attempts_still_report_the_later_one(self, check):
        """When neither attempt executed, list order still decides which is
        reported -- there is no executed sibling to prefer instead."""
        runs = [_run("a", conclusion="cancelled"), _run("a", conclusion="skipped")]
        verdict = check.evaluate(["a"], runs, require_complete=True)
        assert verdict.not_executed == ["a"] and not verdict.ok


class TestItRefusesToGuess:
    """Reporting green because it could not tell is the one outcome that would
    make this gate actively harmful."""

    def test_an_unparseable_payload_fails(self, check, tmp_path, capsys):
        bad = tmp_path / "check-runs.json"
        bad.write_text("{not json", encoding="utf-8")
        assert check.main(["--check-runs", str(bad)]) == 1
        assert "unmeasured" in capsys.readouterr().out

    def test_a_missing_payload_fails(self, check, tmp_path, capsys):
        missing = tmp_path / "nope.json"
        assert check.main(["--check-runs", str(missing)]) == 1
        assert "unmeasured" in capsys.readouterr().out

    def test_a_payload_without_the_array_fails(self, check, tmp_path, capsys):
        bad = tmp_path / "check-runs.json"
        bad.write_text(json.dumps({"total_count": 0}), encoding="utf-8")
        assert check.main(["--check-runs", str(bad)]) == 1
        assert "unmeasured" in capsys.readouterr().out

    def test_an_empty_check_list_is_pending_not_a_pass(self, check, tmp_path):
        """Zero checks is never green, but a live queue must wait for evidence."""
        assert check.main(["--check-runs", str(_payload(tmp_path, []))]) == check.PENDING_EXIT

    def test_a_bare_array_is_accepted_too(self, check, tmp_path):
        """Some callers hand over the array rather than the envelope; refusing
        that would be a parse failure masquerading as a finding."""
        path = tmp_path / "check-runs.json"
        path.write_text(json.dumps([_run("x")]), encoding="utf-8")
        assert check._load(path) == [_run("x")]


class TestTheRequiredSet:
    def test_it_reads_the_existing_contract(self, check):
        """Not a second list. `check-required-checks.py` already keeps these
        honest against the workflows, and a name in two places drifts in one."""
        names = check.required_check_names()
        assert "workflow-lint" in names
        assert [n for n in names if n.startswith("Quality gate")]

    def test_base_coupled_checks_are_excluded(self, check):
        """CodeQL runs only on PRs based on `main`, so on a develop PR it
        legitimately produces no run. Requiring it would paint every PR in the
        repository red for correct behaviour, and the gate would be switched off
        within a day."""
        names = check.required_check_names()
        assert not [n for n in names if n.startswith("Analyze (")]
        assert "Container scan + SBOM + cosign" not in names

    def test_the_real_contract_passes_against_a_fully_green_head(self, check, tmp_path):
        """End to end on the actual required set, the way the workflow runs it."""
        runs = [_run(name) for name in check.required_check_names()]
        assert (
            check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"]) == 0
        )

    def test_one_missing_check_is_pending_for_the_real_contract(self, check, tmp_path, capsys):
        names = check.required_check_names()
        runs = [_run(name) for name in names[1:]]
        assert (
            check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"])
            == check.PENDING_EXIT
        )
        out = capsys.readouterr().out
        assert "not present yet" in out
        assert names[0] in out

    def test_one_skipped_check_fails_the_real_contract(self, check, tmp_path, capsys):
        """Presence of a skipped required check must never make the aggregate green."""
        names = check.required_check_names()
        runs = [_run(name) for name in names]
        runs[0] = _run(names[0], conclusion="skipped")
        assert (
            check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"]) == 1
        )
        out = capsys.readouterr().out
        assert "did not execute to a verdict" in out
        assert names[0] in out


class TestTheWorkflowItself:
    def test_it_passes_the_write_safety_guard(self):
        """The gate added beside it in the same change. A new workflow that
        tripped it would be a poor advertisement."""
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check-workflow-write-safety.py")],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_it_triggers_on_every_workflow_that_produces_a_required_check(self):
        """A workflow missing from the trigger list means its completion never
        re-evaluates the head, so the last word could be an early pending state."""
        import yaml

        doc = yaml.safe_load((ROOT / ".github" / "workflows" / "gates-ran.yml").read_text())
        on = doc.get(True) or doc.get("on")
        triggers = set(on["workflow_run"]["workflows"])

        spec = importlib.util.spec_from_file_location(
            "crc", ROOT / "scripts" / "check-required-checks.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["crc"] = module
        spec.loader.exec_module(module)
        producers = {workflow for workflow, _name, _scope in module.collect()}

        assert producers - triggers == set(), "a producer workflow is not a trigger"


class TestPathScopedRequiredChecks:
    def test_a_non_specialized_path_scoped_check_can_be_skipped(self, check, monkeypatch):
        """The skip rule is generic: it is not a hard-coded specialized-job list."""
        monkeypatch.setitem(check.PATH_SCOPED_CHECKS, "coverage (path-gated)", "postgres")
        verdict = check.evaluate(
            ["coverage (path-gated)", "always-required"],
            [
                _run("coverage (path-gated)", conclusion="skipped"),
                _run("always-required", conclusion="skipped"),
            ],
            require_complete=True,
            scope={"postgres": False},
            scope_measured=True,
        )
        assert verdict.not_executed == ["always-required"]
        assert verdict.ok is False

    def test_an_out_of_scope_failure_is_still_a_finding(self, check, monkeypatch):
        monkeypatch.setitem(check.PATH_SCOPED_CHECKS, "coverage (path-gated)", "postgres")
        verdict = check.evaluate(
            ["coverage (path-gated)"],
            [_run("coverage (path-gated)", conclusion="failure")],
            require_complete=True,
            scope={"postgres": False},
            scope_measured=True,
        )
        assert verdict.not_executed == []
        assert verdict.ran == ["coverage (path-gated)"]

    def test_unmeasured_scope_keeps_path_scoped_skip_pending(self, check, monkeypatch):
        monkeypatch.setitem(check.PATH_SCOPED_CHECKS, "coverage (path-gated)", "postgres")
        verdict = check.evaluate(
            ["coverage (path-gated)"],
            [_run("coverage (path-gated)", conclusion="skipped")],
            require_complete=True,
            scope=None,
            scope_measured=False,
        )
        assert verdict.unfinished == ["coverage (path-gated)"]
        assert verdict.pending and not verdict.ok


class TestTheCliScopeEnvelope:
    """The workflow hands the CLI a measured changed-file envelope next to the
    check-run payload. Between the argparse surface and evaluate() sit the
    lines that load the scope classifier, refuse to guess when the envelope is
    missing or unmeasured, and honor a measured out-of-scope skip -- none of
    which a direct evaluate() call can reach."""

    @staticmethod
    def _runs_for_scope(check, legs_off: set[str]) -> list[dict]:
        """Every required check either ran, or is skipped because the measured
        scope says its leg was never reachable -- the shape a PR that cannot
        affect a leg produces when CI correctly skips it."""
        runs = []
        for name in check.required_check_names(event_name="pull_request"):
            leg = check.PATH_SCOPED_CHECKS.get(name)
            conclusion = "skipped" if leg is not None and leg in legs_off else "success"
            runs.append(_run(name, conclusion=conclusion))
        return runs

    def test_a_measured_deps_only_envelope_excuses_out_of_scope_skips(
        self, check, tmp_path, capsys
    ):
        """A PR touching nothing any specialized leg reads (release notes) may
        legitimately skip all of them; with a measured envelope saying so, the
        skipped legs must not be findings."""
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
                "--changed-files",
                str(_envelope(tmp_path, {"measured": True, "files": ["notes/todo.txt"]})),
            ]
        )
        assert code == 0
        assert "ok: all" in capsys.readouterr().out

    def test_an_in_scope_skip_still_fails_with_a_measured_envelope(self, check, tmp_path, capsys):
        """The envelope excuses skips the scope proves unreachable, never ones it
        proves reachable: uv.lock is a global file, every leg runs on it, so a
        skipped leg there really did not execute."""
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
                "--changed-files",
                str(_envelope(tmp_path, {"measured": True, "files": ["uv.lock"]})),
            ]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "FAIL: the gate set did not reach this commit" in out
        assert "did not execute to a verdict" in out

    def test_a_pull_request_without_a_measured_envelope_is_pending(self, check, tmp_path, capsys):
        """pull_request with no --changed-files: the skip evidence cannot be
        judged, so the verdict must be pending rather than green or red."""
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
            ]
        )
        out = capsys.readouterr().out
        assert code == check.PENDING_EXIT
        assert "changed files were not measured" in out

    def test_an_envelope_that_was_never_measured_is_pending(self, check, tmp_path, capsys):
        """`measured` must be literally true; anything else is the same
        ambiguity as no envelope at all."""
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
                "--changed-files",
                str(_envelope(tmp_path, {"measured": False, "files": ["notes/todo.txt"]})),
            ]
        )
        out = capsys.readouterr().out
        assert code == check.PENDING_EXIT
        assert "changed-file payload is invalid" in out

    def test_an_envelope_with_non_string_files_is_pending(self, check, tmp_path, capsys):
        """A files array holding a non-string is not an envelope this gate can
        interpret; guessing either way would be fabrication."""
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
                "--changed-files",
                str(_envelope(tmp_path, {"measured": True, "files": ["notes/todo.txt", 7]})),
            ]
        )
        out = capsys.readouterr().out
        assert code == check.PENDING_EXIT
        assert "changed-file payload is invalid" in out

    def test_an_unreadable_envelope_is_pending(self, check, tmp_path, capsys):
        """A corrupt envelope file is unmeasured scope, not a pass."""
        bad = tmp_path / "changed-files.json"
        bad.write_text("{not json", encoding="utf-8")
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
                "--changed-files",
                str(bad),
            ]
        )
        out = capsys.readouterr().out
        assert code == check.PENDING_EXIT
        assert "execution scope is ambiguous" in out

    def test_an_unloadable_scope_classifier_degrades_to_pending(
        self, check, tmp_path, capsys, monkeypatch
    ):
        """If the classifier module cannot even be loaded, the envelope cannot be
        judged -- that packaging accident must surface as pending scope, never
        as a crash or a green guess."""
        real_spec = importlib.util.spec_from_file_location

        def _broken_scope_loader(name, *args, **kwargs):
            return None if "scope" in name else real_spec(name, *args, **kwargs)

        monkeypatch.setattr("importlib.util.spec_from_file_location", _broken_scope_loader)
        every_leg = set(check.PATH_SCOPED_CHECKS.values())
        code = check.main(
            [
                "--check-runs",
                str(_payload(tmp_path, self._runs_for_scope(check, every_leg))),
                "--require-complete",
                "--event-name",
                "pull_request",
                "--changed-files",
                str(_envelope(tmp_path, {"measured": True, "files": ["notes/todo.txt"]})),
            ]
        )
        out = capsys.readouterr().out
        assert code == check.PENDING_EXIT
        assert "execution scope is ambiguous" in out


class TestTheReport:
    """A gate is read by someone deciding whether to trust a merge, so what it
    prints is part of what it does."""

    def test_non_executed_checks_are_reported_separately_from_absent_ones(
        self, check, tmp_path, capsys
    ):
        """They are different diagnoses: absent means no run record exists;
        non-executed means one exists but cannot certify enforcement."""
        names = check.required_check_names()
        runs = [_run(n) for n in names]
        runs[0] = _run(names[0], conclusion="action_required")
        code = check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"])
        out = capsys.readouterr().out
        assert code == 1
        assert "did not execute to a verdict" in out
        assert names[0] in out
        assert "not present yet" not in out

    def test_unfinished_checks_are_reported_as_pending(self, check, tmp_path, capsys):
        names = check.required_check_names()
        runs = [_run(n) for n in names]
        runs[0] = _run(names[0], status="in_progress", conclusion=None)
        code = check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"])
        out = capsys.readouterr().out
        assert code == check.PENDING_EXIT
        assert "PENDING" in out
        assert "started but not finished" in out

    def test_a_scalar_payload_is_refused(self, check, tmp_path, capsys):
        """Not an object and not an array. Refused rather than coerced, for the
        same reason as every other unreadable shape."""
        bad = tmp_path / "check-runs.json"
        bad.write_text("5", encoding="utf-8")
        assert check.main(["--check-runs", str(bad)]) == 1
        assert "unmeasured" in capsys.readouterr().out

    def test_an_empty_required_set_is_refused(self, check, tmp_path, monkeypatch, capsys):
        """If the contract ever came back empty this gate would pass everything
        while appearing to check. That is the failure it exists to prevent, one
        level up."""
        monkeypatch.setattr(check, "required_check_names", lambda **_kwargs: [])
        assert check.main(["--check-runs", str(_payload(tmp_path, [_run("x")]))]) == 1
        assert "contract is empty" in capsys.readouterr().out

    def test_the_script_entry_point_judges_a_green_head(self, check, tmp_path):
        """The `python3 scripts/check-gates-ran.py` invocation the workflow
        actually runs -- argparse on real argv, exit code through the shell --
        rather than the imported main() every other test uses."""
        runs = [_run(name) for name in check.required_check_names()]
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--check-runs",
                str(_payload(tmp_path, runs)),
                "--require-complete",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "ok: all" in proc.stdout
