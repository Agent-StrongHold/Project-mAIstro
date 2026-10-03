"""M5-B (#108) — the weighted proven-scenario objective inside the RSI fitness.

Pins the Scorecard wiring: configuring a scenario objective adds the
``no_proven_scenario_regression`` veto and the dominant ``proven_scenarios``
scalar signal; the correctness oracle (the ``tests_pass`` gate by default, or
an injected broader verdict) and the scalar stay recorded separately; and no
combination of unrelated signal gains can compensate a correctness failure or
a proven-scenario regression.

Pure ``compose_scorecard`` tests — no tool runs.
"""

from __future__ import annotations

import pytest

from maistro_evolve.scenario_objective import (
    CorrectnessResult,
    ScenarioCriticality,
    ScenarioDefinition,
    ScenarioObjective,
)
from maistro_evolve.scorecard import FitnessWeights
from maistro_evolve.tdd_gate import TddEvidence
from maistro_rsi.candidate_fitness import FitnessInputs, compose_scorecard


def _scenario_objective() -> ScenarioObjective:
    """security 4.0 > product 2.0 > cosmetic 1.0 — the M5-B criticality
    ladder, in one objective."""
    return ScenarioObjective(
        version="scenario-obj-v1",
        scenarios=(
            ScenarioDefinition(
                scenario_id="sec/data-exfiltration",
                title="Agent must never exfiltrate secrets",
                criticality=ScenarioCriticality.SECURITY,
                weight=4.0,
            ),
            ScenarioDefinition(
                scenario_id="prod/checkout",
                title="User can complete checkout",
                criticality=ScenarioCriticality.PRODUCT,
                weight=2.0,
            ),
            ScenarioDefinition(
                scenario_id="cosmetic/typo",
                title="Landing page typo fixed",
                criticality=ScenarioCriticality.COSMETIC,
                weight=1.0,
            ),
        ),
    )


_PROVEN = {"sec/data-exfiltration": 1.0, "prod/checkout": 0.5, "cosmetic/typo": 0.0}
_CANDIDATE = {"sec/data-exfiltration": 1.0, "prod/checkout": 0.5, "cosmetic/typo": 0.0}


def test_no_scenario_objective_adds_no_gate_or_signal() -> None:
    """Absent scenario evidence adds no gate (never a false rejection)."""
    sc = compose_scorecard(FitnessInputs(tests_passed=True))
    assert sc.scenario_objective is None
    assert "no_proven_scenario_regression" not in {g.name for g in sc.gates}
    assert "proven_scenarios" not in {s.name for s in sc.scores}
    assert sc.accepted is True


def test_scenario_gate_and_signal_present_when_configured() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            scenario_objective=_scenario_objective(),
            scenario_proven_scores=_PROVEN,
            scenario_candidate_scores=_CANDIDATE,
        )
    )
    gate = next(g for g in sc.gates if g.name == "no_proven_scenario_regression")
    assert gate.passed is True
    # The evaluation record rides on the Scorecard: correctness verdict and
    # scalar score recorded separately from the work-signal composite.
    record = sc.scenario_objective
    assert record is not None
    assert record.correctness_gate.passed is True
    assert record.objective_score == pytest.approx(5.0 / 7.0)
    assert record.promotable is True
    assert record.objective_digest == _scenario_objective().digest()
    signal = next(s for s in sc.scores if s.name == "proven_scenarios")
    assert signal.score == pytest.approx(5.0 / 7.0)


def test_default_correctness_oracle_is_the_tests_pass_gate() -> None:
    """A red test suite zeroes the scenario objective: correctness failure →
    scalar 0.0 and no promotion, even with unchanged (passing) scenarios."""
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=False,
            test_reason="exit 1: 2 failed",
            scenario_objective=_scenario_objective(),
            scenario_proven_scores=_PROVEN,
            scenario_candidate_scores=_CANDIDATE,
        )
    )
    gate = next(g for g in sc.gates if g.name == "no_proven_scenario_regression")
    assert gate.passed is False
    assert "correctness=FAIL" in gate.reason
    record = sc.scenario_objective
    assert record is not None
    assert record.correctness_gate.passed is False
    assert record.correctness_gate.failures == ("exit 1: 2 failed",)
    assert record.objective_score == 0.0
    assert sc.accepted is False
    assert sc.composite == 0.0


def test_injected_correctness_verdict_can_veto_beyond_tests_pass() -> None:
    """A broader oracle (security suite, contract tests) may fail the
    correctness gate even when the loop's own pytest run was green — and its
    verdict, not a numeric substitution, decides."""
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            scenario_objective=_scenario_objective(),
            scenario_proven_scores=_PROVEN,
            scenario_candidate_scores=_CANDIDATE,
            scenario_correctness=CorrectnessResult(
                passed=False, failures=("security suite: 1 HIGH",)
            ),
        )
    )
    gate = next(g for g in sc.gates if g.name == "no_proven_scenario_regression")
    assert gate.passed is False
    record = sc.scenario_objective
    assert record is not None
    assert record.correctness_gate.failures == ("security suite: 1 HIGH",)
    assert record.objective_score == 0.0
    assert sc.accepted is False
    assert sc.composite == 0.0


def test_scenario_regression_vetoes_despite_maxed_unrelated_signals() -> None:
    """Acceptance 3 at the fitness layer: a security scenario regresses while
    every unrelated work signal is at its best — the veto holds and the
    composite is zero, so no unrelated scalar gain buys the promotion."""
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            # Strong unrelated evidence: test-first change, quality, coverage.
            tdd=TddEvidence(
                changed_tests=["tests/test_x.py"],
                baseline_changed_rc=1,
                candidate_changed_rc=0,
            ),
            code_quality_composite=0.95,
            baseline_coverage=80.0,
            candidate_coverage=84.0,
            scenario_objective=_scenario_objective(),
            scenario_proven_scores=_PROVEN,
            # The security scenario slipped; the cosmetic one was perfected.
            scenario_candidate_scores={
                "sec/data-exfiltration": 0.6,
                "prod/checkout": 1.0,
                "cosmetic/typo": 1.0,
            },
        )
    )
    gate = next(g for g in sc.gates if g.name == "no_proven_scenario_regression")
    assert gate.passed is False
    assert "regressed sec/data-exfiltration" in gate.reason
    assert sc.accepted is False
    # A vetoed candidate has no composite to compete with: 0.0, full stop.
    assert sc.composite == 0.0


def test_proven_scenarios_is_the_dominant_scalar() -> None:
    """The criticality-weighted scenario score outranks every work signal —
    keeping the proven scenarios green IS the objective the signals serve."""
    w = FitnessWeights()
    others = [
        w.spec_completion,
        w.spec_proposed,
        w.new_test,
        w.capability,
        w.assertion_strength,
        w.mutation_strength,
        w.red_green,
        w.feature_judge,
        w.coverage,
        w.architecture_fit,
        w.personalized_judge,
        w.perf,
        w.code_quality,
    ]
    assert w.proven_scenarios > max(others)

    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            scenario_objective=_scenario_objective(),
            scenario_proven_scores=_PROVEN,
            scenario_candidate_scores=_CANDIDATE,
        )
    )
    # Literal composite pin: only red_green (0.5 score * 0.14) joins the
    # scenario signal, so composite = round(((5/7)*0.50 + 0.5*0.14) / 0.64, 4).
    expected = round(((5.0 / 7.0) * 0.50 + 0.5 * 0.14) / 0.64, 4)
    assert sc.composite == expected
    assert sc.composite == 0.6674


def test_gate_detail_records_gate_and_scalar_separately() -> None:
    sc = compose_scorecard(
        FitnessInputs(
            tests_passed=True,
            scenario_objective=_scenario_objective(),
            scenario_proven_scores=_PROVEN,
            scenario_candidate_scores=_CANDIDATE,
        )
    )
    gate = next(g for g in sc.gates if g.name == "no_proven_scenario_regression")
    assert gate.detail["correctness_passed"] is True
    assert gate.detail["correctness_failures"] == []
    assert gate.detail["objective_score"] == pytest.approx(5.0 / 7.0)
    assert gate.detail["raw_weighted_score"] == pytest.approx(5.0 / 7.0)
    assert gate.detail["objective_version"] == "scenario-obj-v1"
