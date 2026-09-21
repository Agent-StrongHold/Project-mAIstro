"""Tests for the fitness composition (pure compose_scorecard; no tool runs)."""

from __future__ import annotations

from maistro_evolve.scorecard import GateResult
from maistro_evolve.tdd_gate import TddEvidence
from maistro_rsi.candidate_fitness import (
    FitnessInputs,
    InventoryEvidence,
    compose_scorecard,
)
from maistro_rsi.regression_judge import JudgeVerdict
from maistro_rsi.test_inventory import InventoryResult


def test_failing_tests_veto() -> None:
    sc = compose_scorecard(FitnessInputs(tests_passed=False, test_reason="exit 1"))
    assert sc.accepted is False
    assert sc.composite == 0.0


def test_coverage_drop_vetoes() -> None:
    sc = compose_scorecard(
        FitnessInputs(tests_passed=True, baseline_coverage=80.0, candidate_coverage=70.0)
    )
    assert sc.accepted is False


def test_lint_gate_vetoes() -> None:
    sc = compose_scorecard(
        FitnessInputs(tests_passed=True, lint_gates=[GateResult("ruff_clean", False, "3 issues")])
    )
    assert sc.accepted is False


def test_all_gates_pass_scores_and_accepts() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            baseline_coverage=80.0,
            candidate_coverage=82.0,
            code_quality_composite=0.8,
            assertion_score=0.7,
            tdd=TddEvidence(changed_tests=["t.py"], baseline_changed_rc=1, candidate_changed_rc=0),
        )
    )
    assert sc.accepted is True
    assert sc.composite > 0.0
    names = {s.name for s in sc.scores}
    assert {"red_green", "coverage", "assertion_strength", "code_quality"} <= names


def test_syntax_error_vetoes() -> None:
    sc = compose_scorecard(
        FitnessInputs(tests_passed=True, syntax_error_reasons=["bad.py: invalid syntax (line 3)"])
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "valid_syntax")
    assert gate.passed is False and "bad.py" in gate.reason


def test_uncollectable_test_vetoes() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            uncollectable_test_reasons=["src/test_x.py: outside configured test roots (tests)"],
        )
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "tests_collectable")
    assert gate.passed is False


def test_vacuous_test_vetoes() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            vacuous_test_reasons=["test_x.py: still passes with src.py reverted"],
        )
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "test_exercises_change")
    assert gate.passed is False


def test_flagged_regression_vetoes_below_threshold() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            regression_judge=JudgeVerdict(
                status="reject", score=0.2, rationale="narrows list to str()"
            ),
        )
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "no_flagged_regression")
    assert gate.passed is False and "narrows list to str()" in gate.reason
    assert gate.detail["score"] == 0.2


def test_regression_judge_above_threshold_passes() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            regression_judge=JudgeVerdict(status="pass", score=0.9, rationale="no concerns"),
        )
    )
    gate = next(g for g in sc.gates if g.name == "no_flagged_regression")
    assert gate.passed is True
    assert sc.accepted is True


def test_unavailable_judge_fails_the_gate_fail_closed() -> None:
    # #307: an unavailable judge (here: gateway error) is a FAILED gate with
    # the cause in the reason — the candidate is NOT accepted, and the
    # scorecard's judge score stays None rather than a passing fallback.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            regression_judge=JudgeVerdict(
                status="unavailable",
                score=None,
                rationale="judge gateway error",
                cause="gateway_error",
            ),
        )
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "no_flagged_regression")
    assert gate.passed is False
    assert "gateway_error" in gate.reason
    assert gate.detail["score"] is None


def test_unavailable_judge_cause_named_in_gate_reason() -> None:
    for cause in ("gateway_error", "timeout", "unparsable_reply", "oversized_diff"):
        sc = compose_scorecard(
            FitnessInputs(
                tests_passed=True,
                regression_judge=JudgeVerdict(
                    status="unavailable", score=None, rationale="judge unavailable", cause=cause
                ),
            )
        )
        assert sc.accepted is False, cause
        gate = next(g for g in sc.gates if g.name == "no_flagged_regression")
        assert gate.passed is False and cause in gate.reason, cause


def test_regression_judge_absent_by_default_no_gate_added() -> None:
    sc = compose_scorecard(FitnessInputs(tests_passed=True))
    assert not any(g.name == "no_flagged_regression" for g in sc.gates)


def test_new_gates_pass_by_default_when_all_gates_pass() -> None:
    # The default-empty new fields must not break the existing green path.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            baseline_coverage=80.0,
            candidate_coverage=82.0,
        )
    )
    assert sc.accepted is True


def test_refactor_accepted_and_rewarded_by_code_quality() -> None:
    # No test change, tests pass, coverage held, quality up -> accepted; the
    # code_quality score carries it, red_green is the neutral 0.5.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            baseline_coverage=80.0,
            candidate_coverage=80.0,
            code_quality_composite=0.9,
        )
    )
    assert sc.accepted is True
    rg = next(s for s in sc.scores if s.name == "red_green")
    assert rg.score == 0.5
    assert any(s.name == "code_quality" for s in sc.scores)


# --- protected test inventory (#306) -----------------------------------------
#
# The gate is ALWAYS present; these construct the evidence directly (the
# collection itself is exercised for real in test_test_inventory.py, and the
# skip-marker path through differential collection in
# test_newly_added_skip_marker_reads_as_a_deletion there).


def _inv_evidence(
    base: set[str] | None,
    cand: set[str],
    *,
    cand_ok: bool = True,
    config_changed: list[str] | None = None,
    allow_shrink: bool = False,
    cand_collected: set[str] | None = None,
) -> InventoryEvidence:
    return InventoryEvidence(
        candidate=InventoryResult(
            collected=cand_collected if cand_collected is not None else set(cand),
            servable=set(cand),
            collection_ok=cand_ok,
            collection_error=None if cand_ok else "full pass exit 2: boom",
        ),
        base=None if base is None else InventoryResult(collected=set(base), servable=set(base)),
        config_files_changed=config_changed or [],
        allow_shrink=allow_shrink,
    )


def _inventory_gate(sc) -> object:  # type: ignore[no-untyped-def]
    return next(g for g in sc.gates if g.name == "protected_test_inventory")


def test_inventory_gate_is_always_present() -> None:
    # ALWAYS-ON (#306): unlike the conditional gates, the inventory gate exists
    # in every scorecard — here with no evidence at all (a compose-only call),
    # passing because there is no measurement to fail on.
    sc = compose_scorecard(FitnessInputs(tests_passed=True))
    gate = _inventory_gate(sc)
    assert gate.passed is True
    assert sc.accepted is True


def test_inventory_deletion_vetoes_and_rejects_candidate() -> None:
    # Base has 2 tests, candidate deletes 1: count moved 2 -> 1, but the veto
    # is on the deleted IDENTITY, not the count.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence({"t.py::a", "t.py::b"}, {"t.py::b"}),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert "t.py::a" in gate.reason
    assert gate.detail["deleted"] == ["t.py::a"]
    assert gate.detail["deleted_count"] == 1
    assert sc.accepted is False


def test_inventory_additions_do_not_outweigh_deletions() -> None:
    # +3 added, -2 deleted: the net count grew and the candidate still fails —
    # the count is never the oracle, the deleted IDs are.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence({"t.py::a", "t.py::b"}, {"t.py::c", "t.py::d", "t.py::e"}),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert len(gate.detail["deleted"]) == 2
    assert sc.accepted is False


def test_inventory_rename_vetoes_via_the_old_identity() -> None:
    # A rename is the old ID deleted plus the new one added — fails exactly
    # like a deletion.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence({"t.py::test_old"}, {"t.py::test_new"}),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert gate.detail["deleted"] == ["t.py::test_old"]
    assert gate.detail["added"] == ["t.py::test_new"]


def test_inventory_newly_skip_gated_test_vetoes() -> None:
    # The ID still collects (skip marker, not deletion) but left the servable
    # set — the differential-collection path (see test_test_inventory.py)
    # produces exactly this evidence shape.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence(
                {"t.py::a", "t.py::b"},
                {"t.py::b"},
                cand_collected={"t.py::a", "t.py::b"},
            ),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert gate.detail["deleted"] == ["t.py::a"]
    assert sc.accepted is False


def test_inventory_collection_failure_vetoes() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence({"t.py::a"}, set(), cand_ok=False),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert "inventory unverifiable: collection failed" in gate.reason
    assert sc.accepted is False


def test_inventory_collection_failure_vetoes_even_without_a_base() -> None:
    # ALWAYS-ON rule 1: the candidate's own broken collection is disqualifying
    # on its own — no baseline needed to know the oracle can't be verified.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence(None, set(), cand_ok=False),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert "collection failed" in gate.reason


def test_inventory_base_collection_failure_fails_closed() -> None:
    base = InventoryResult(
        collected={"t.py::a"}, servable={"t.py::a"}, collection_ok=False, collection_error="boom"
    )
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=InventoryEvidence(
                candidate=InventoryResult(collected={"t.py::a"}, servable={"t.py::a"}),
                base=base,
            ),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert "base collection failed" in gate.reason


def test_inventory_shrink_override_passes_and_records_deleted_ids() -> None:
    # The governance override (allow_test_inventory_shrink): the gate passes,
    # but never silently — reason, detail override flag, and the deleted list
    # all record exactly what was allowed.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence({"t.py::a", "t.py::b"}, {"t.py::b"}, allow_shrink=True),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is True
    assert sc.accepted is True
    assert gate.detail["override"] is True
    assert gate.detail["deleted"] == ["t.py::a"]
    assert "GOVERNANCE OVERRIDE" in gate.reason
    assert "t.py::a" in gate.reason


def test_inventory_config_change_plus_shrink_presumes_hiding() -> None:
    # Config edit (here: pyproject addopts) that shrinks the collected set —
    # the config change itself is the hiding mechanism.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence(
                {"t.py::a", "t.py::b"},
                {"t.py::a"},
                config_changed=["pyproject.toml"],
            ),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert "presumed hiding" in gate.reason
    assert "pyproject.toml" in gate.reason
    assert gate.detail["config_files_changed"] == ["pyproject.toml"]


def test_inventory_config_change_plus_shrink_not_covered_by_override() -> None:
    # The override authorizes a plain shrink; config-plus-shrink is presumed
    # hiding and vetoes regardless.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence(
                {"t.py::a", "t.py::b"},
                {"t.py::a"},
                config_changed=["tests/conftest.py"],
                allow_shrink=True,
            ),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert sc.accepted is False


def test_inventory_config_change_with_additions_only_passes() -> None:
    # A legitimate config edit (e.g. registering a marker) that ADDS tests:
    # nothing shrank, so it passes.
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence(
                {"t.py::a"}, {"t.py::a", "t.py::new"}, config_changed=["pytest.ini"]
            ),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is True
    assert sc.accepted is True
    assert gate.detail["base"] == 1
    assert gate.detail["candidate"] == 2
    assert gate.detail["deleted"] == []


def test_inventory_clean_candidate_passes_with_counts() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence({"t.py::a"}, {"t.py::a"}),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is True
    assert sc.accepted is True
    assert gate.detail == {
        "base": 1,
        "candidate": 1,
        "deleted": [],
        "deleted_count": 0,
        "added": [],
    }


def test_inventory_deleted_list_capped_at_20_in_the_trace() -> None:
    deleted = {f"t.py::test_{i:02d}" for i in range(50)}
    kept = {"t.py::kept"}
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            test_inventory=_inv_evidence(deleted | kept, kept),
        )
    )
    gate = _inventory_gate(sc)
    assert gate.passed is False
    assert len(gate.detail["deleted"]) == 20  # capped for the trace
    assert gate.detail["deleted_count"] == 50  # the full count still recorded
