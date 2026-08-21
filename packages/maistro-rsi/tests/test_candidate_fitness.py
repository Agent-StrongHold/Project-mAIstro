"""Tests for the fitness composition (pure compose_scorecard; no tool runs)."""

from __future__ import annotations

from maistro_evolve.scorecard import GateResult
from maistro_evolve.tdd_gate import TddEvidence
from maistro_rsi.candidate_fitness import FitnessInputs, compose_scorecard


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
        FitnessInputs(tests_passed=True, regression_judge=(0.2, "narrows list to str()"))
    )
    assert sc.accepted is False
    gate = next(g for g in sc.gates if g.name == "no_flagged_regression")
    assert gate.passed is False and "narrows list to str()" in gate.reason


def test_regression_judge_above_threshold_passes() -> None:
    sc = compose_scorecard(FitnessInputs(tests_passed=True, regression_judge=(0.9, "no concerns")))
    gate = next(g for g in sc.gates if g.name == "no_flagged_regression")
    assert gate.passed is True


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
