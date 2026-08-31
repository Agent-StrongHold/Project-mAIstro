from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"
spec = importlib.util.spec_from_file_location("_ac_state_review_slack", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


def _canonical_develop_ci(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Agent-StrongHold/Project-mAIstro")
    monkeypatch.setenv("GITHUB_BASE_REF", "develop")


def test_canonical_develop_pr_improvement_is_informational(monkeypatch, capsys):
    _canonical_develop_ci(monkeypatch)
    monkeypatch.setattr(gate, "_candidate_note_fold_weakening", lambda: [])

    assert gate._review_slack_policy(["design_coverage: 31.7, floor still says 31.2"]) == []

    out = capsys.readouterr().out
    assert "no bank is required" in out
    assert "live develop merge queue serializes the exact candidate" in out


def test_imported_or_synthetic_pr_keeps_conservative_banking(monkeypatch):
    seen: list[list[str]] = []

    def original(improvements: list[str]) -> list[str]:
        seen.append(improvements)
        return ["still-blocked"]

    monkeypatch.setattr(gate, "_ORIGINAL_SLACK_POLICY", original)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Agent-StrongHold/Project-mAIstro")
    monkeypatch.setenv("GITHUB_BASE_REF", "develop")
    monkeypatch.setattr(sys, "argv", ["pytest"])

    assert gate._review_slack_policy(["x"]) == ["still-blocked"]
    assert seen == [["x"]]


def test_direct_front_door_fails_closed_when_path_resolution_fails(monkeypatch):
    def fail_resolve(_path):
        raise OSError("unresolvable path")

    monkeypatch.setattr(gate.Path, "resolve", fail_resolve)

    assert gate._direct_front_door() is False


def test_candidate_note_fold_reports_missing_bounded_counter(monkeypatch):
    monkeypatch.setattr(gate._impl, "RATCHETED", ("debt",))
    monkeypatch.setattr(gate._impl, "FLOORED", ("progress",))
    monkeypatch.setattr(
        gate._impl.ac_state_notes,
        "bounds",
        lambda: SimpleNamespace(base_sha="trusted", counters={"debt": 2, "progress": 20}),
    )
    monkeypatch.setattr(gate._impl, "authorized_floors", lambda _sha: ({}, []))
    monkeypatch.setattr(
        gate._impl,
        "_banked",
        lambda: SimpleNamespace(counters={"debt": 2}),
    )
    monkeypatch.setattr(gate._impl, "_lowered", lambda counters, _floors: counters)

    assert gate._candidate_note_fold_weakening() == [
        "candidate note fold omits bounded counter progress"
    ]


def test_candidate_note_fold_compares_candidate_with_authorized_trusted_fold(monkeypatch):
    trusted = {"debt": 2, "progress": 20}
    lowered = {"debt": 2, "progress": 18}
    candidate = {"debt": 2, "progress": 19}
    seen: list[tuple[dict[str, int], dict[str, int]]] = []

    monkeypatch.setattr(gate._impl, "RATCHETED", ("debt",))
    monkeypatch.setattr(gate._impl, "FLOORED", ("progress",))
    monkeypatch.setattr(
        gate._impl.ac_state_notes,
        "bounds",
        lambda: SimpleNamespace(base_sha="trusted", counters=trusted),
    )
    monkeypatch.setattr(gate._impl, "authorized_floors", lambda _sha: ({"progress": 18}, []))
    monkeypatch.setattr(
        gate._impl,
        "_banked",
        lambda: SimpleNamespace(counters=candidate),
    )
    monkeypatch.setattr(gate._impl, "_lowered", lambda _counters, _floors: lowered)

    def compare(base, worktree):
        seen.append((base, worktree))
        return (["weakened"], ["improved"])

    monkeypatch.setattr(gate._impl, "_compare", compare)

    assert gate._candidate_note_fold_weakening() == ["weakened"]
    assert seen == [(lowered, candidate)]


def test_candidate_note_weakening_is_not_excused_as_measurement_slack(monkeypatch, capsys):
    _canonical_develop_ci(monkeypatch)
    monkeypatch.setattr(
        gate,
        "_candidate_note_fold_weakening",
        lambda: ["design_coverage: 15 falls below the floor of 20"],
    )

    improvements = ["design_coverage: 20, floor still says 15"]
    assert gate._review_slack_policy(improvements) == improvements

    out = capsys.readouterr().out
    assert "candidate AC-state notes weaken the trusted base fold" in out
    assert "cannot authorize edits to inherited note evidence" in out


def test_merge_group_keeps_existing_slack_policy_after_note_validation(monkeypatch):
    seen: list[list[str]] = []

    def original(improvements: list[str]) -> list[str]:
        seen.append(improvements)
        return ["merge-policy-result"]

    monkeypatch.setattr(gate, "_ORIGINAL_SLACK_POLICY", original)
    monkeypatch.setattr(gate, "_candidate_note_fold_weakening", lambda: [])
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")

    assert gate._review_slack_policy(["x"]) == ["merge-policy-result"]
    assert seen == [["x"]]


def test_relaxed_success_wording_claims_bounds_not_exact_equality():
    exact = (
        f"OK: {len(gate._impl.RATCHETED)} debt counters sit exactly on their ceilings and "
        f"{len(gate._impl.FLOORED)} progress counter sits exactly on its floor (base)\n"
    )

    rewritten = gate._rewrite_relaxed_success(exact)

    assert "sit exactly" not in rewritten
    assert "sits exactly" not in rewritten
    assert "debt counters satisfy their ceilings" in rewritten
    assert "progress counter satisfies its floor" in rewritten


def test_relaxed_output_policy_captures_and_rewrites_success(monkeypatch, capsys):
    _canonical_develop_ci(monkeypatch)
    exact = (
        f"OK: {len(gate._impl.RATCHETED)} debt counters sit exactly on their ceilings and "
        f"{len(gate._impl.FLOORED)} progress counter sits exactly on its floor (base)\n"
    )

    def successful_call():
        print(exact, end="")
        return 7

    assert gate._call_with_output_policy(successful_call) == 7
    out = capsys.readouterr().out
    assert "debt counters satisfy their ceilings" in out
    assert "progress counter satisfies its floor" in out


def test_public_ratchet_installs_and_restores_review_policy(monkeypatch):
    def previous(_improvements: list[str]) -> list[str]:
        return ["previous"]

    def fake_ratchet(_totals, _measured, _bank):
        assert gate._impl._slack_this_run_enforces is gate._review_slack_policy
        return 0

    monkeypatch.setattr(gate._impl, "_slack_this_run_enforces", previous)
    monkeypatch.setattr(gate._impl, "ratchet", fake_ratchet)
    monkeypatch.setattr(sys, "argv", ["pytest"])

    assert gate.ratchet({}, measured=True, bank=False) == 0
    assert gate._impl._slack_this_run_enforces is previous
