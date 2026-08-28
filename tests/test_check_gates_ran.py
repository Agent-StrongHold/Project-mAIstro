"""Tests for the "did the gates actually run" check (#262 AC-2).

The script's job is to tell apart states that can all render as "not green": a
check that ran and failed (someone else's problem), one that is still running
(nobody's problem yet), one that never ran at all, and one whose run record
exists but whose conclusion proves the enforcement did not execute to a verdict.
Only the latter two classes and an unfinished check under `--require-complete`
are findings.

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
        assert v.absent == ["b"] and not v.ok

    def test_action_required_is_the_finding_it_was_written_for(self, check):
        """The exact symptom of a push made with the default GITHUB_TOKEN: a run
        exists, so it looks checked, and it will never execute."""
        v = check.evaluate(
            ["a"],
            [_run("a", status="completed", conclusion="action_required")],
            require_complete=True,
        )
        assert v.not_executed == ["a"] and not v.ok

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

    def test_in_progress_is_a_finding_with_require_complete(self, check):
        """Which is how the workflow_run-triggered job asks once the siblings
        have finished."""
        v = check.evaluate(
            ["a"], [_run("a", status="in_progress", conclusion=None)], require_complete=True
        )
        assert v.unfinished == ["a"] and not v.ok

    def test_a_rerun_is_judged_by_its_latest_attempt(self, check):
        """GitHub keeps every attempt. Judging the first would report a check as
        non-executed forever after someone approved and re-ran it."""
        runs = [_run("a", conclusion="action_required"), _run("a", conclusion="success")]
        assert check.evaluate(["a"], runs, require_complete=True).ok


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

    def test_an_empty_check_list_is_a_finding_not_a_pass(self, check, tmp_path):
        """Zero checks on a head is the most complete version of the defect."""
        assert check.main(["--check-runs", str(_payload(tmp_path, []))]) == 1

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
        # Matched by prefix: the real name contains an en dash, and ruff's
        # RUF001 refuses that character in a literal.
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

    def test_one_missing_check_fails_the_real_contract(self, check, tmp_path, capsys):
        names = check.required_check_names()
        runs = [_run(name) for name in names[1:]]
        assert (
            check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"]) == 1
        )
        out = capsys.readouterr().out
        assert "never ran" in out
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
        re-evaluates the head, so the last word could be an early red."""
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
        assert "never ran" not in out

    def test_unfinished_checks_are_reported_separately_too(self, check, tmp_path, capsys):
        names = check.required_check_names()
        runs = [_run(n) for n in names]
        runs[0] = _run(names[0], status="in_progress", conclusion=None)
        code = check.main(["--check-runs", str(_payload(tmp_path, runs)), "--require-complete"])
        out = capsys.readouterr().out
        assert code == 1
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
        monkeypatch.setattr(check, "required_check_names", lambda: [])
        assert check.main(["--check-runs", str(_payload(tmp_path, [_run("x")]))]) == 1
        assert "contract is empty" in capsys.readouterr().out
