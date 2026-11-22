"""M5-B (#108) — the weighted proven-scenario objective is the RSI ruler.

These tests pin the *ruler*, not just a score: criticality bands make the
weight ordering structural (cosmetic can never outweigh product/security),
correctness and the scalar are recorded separately, a correctness failure or a
proven-scenario regression zeroes the scalar and vetoes promotion regardless
of any aggregate gain, and the objective/evaluation are immutable and
version-stamped so a score states which ruler produced it.

Arithmetic pins use literal expected values so a materially wrong aggregation
mutation (swapped weights, un-clamped scores, tolerance drift, renormalisation
drift) cannot pass by dragging its own expectation along.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro_evolve.scenario_objective import (
    CRITICALITY_WEIGHT_BANDS,
    CorrectnessResult,
    ScenarioCriticality,
    ScenarioDefinition,
    ScenarioObjective,
    ScenarioStatus,
    evaluate_proven_scenarios,
)


def _objective(**overrides: object) -> ScenarioObjective:
    kwargs: dict[str, object] = {
        "version": "scenario-obj-v1",
        "scenarios": (
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
    }
    kwargs.update(overrides)
    return ScenarioObjective(**kwargs)  # type: ignore[arg-type]


def _correctness(passed: bool = True) -> CorrectnessResult:
    return CorrectnessResult(passed=passed, failures=() if passed else ("tests_pass: exit 1",))


class TestCriticalityBands:
    def test_cosmetic_cannot_outweigh_product(self):
        """The structural guarantee behind the acceptance criterion: any valid
        cosmetic weight is strictly below any valid product weight, which is
        strictly below any valid security weight."""
        cosmetic_low, cosmetic_high = CRITICALITY_WEIGHT_BANDS[ScenarioCriticality.COSMETIC]
        product_low, product_high = CRITICALITY_WEIGHT_BANDS[ScenarioCriticality.PRODUCT]
        security_low, _ = CRITICALITY_WEIGHT_BANDS[ScenarioCriticality.SECURITY]
        assert cosmetic_high <= product_low
        assert product_high <= security_low
        # The most overweight cosmetic scenario allowed by the model still
        # loses to the lightest product scenario, which loses to the lightest
        # security scenario.
        max_cosmetic = ScenarioDefinition(
            scenario_id="c", criticality=ScenarioCriticality.COSMETIC, weight=1.99
        )
        min_product = ScenarioDefinition(
            scenario_id="p", criticality=ScenarioCriticality.PRODUCT, weight=2.0
        )
        min_security = ScenarioDefinition(
            scenario_id="s", criticality=ScenarioCriticality.SECURITY, weight=4.0
        )
        assert max_cosmetic.weight < min_product.weight < min_security.weight
        assert cosmetic_low <= max_cosmetic.weight < cosmetic_high

    def test_out_of_band_weight_rejected(self):
        with pytest.raises(ValidationError, match="outside its band"):
            ScenarioDefinition(
                scenario_id="c", criticality=ScenarioCriticality.COSMETIC, weight=2.0
            )
        with pytest.raises(ValidationError, match="outside its band"):
            ScenarioDefinition(scenario_id="p", criticality=ScenarioCriticality.PRODUCT, weight=4.0)
        with pytest.raises(ValidationError, match="outside its band"):
            ScenarioDefinition(
                scenario_id="s", criticality=ScenarioCriticality.SECURITY, weight=3.0
            )
        with pytest.raises(ValidationError, match="outside its band"):
            ScenarioDefinition(
                scenario_id="c", criticality=ScenarioCriticality.COSMETIC, weight=0.5
            )

    def test_band_boundaries_are_half_open(self):
        """The lower bound is inclusive, the upper bound is not — the
        exclusivity is what guarantees the strict tier ordering."""
        low, high = CRITICALITY_WEIGHT_BANDS[ScenarioCriticality.PRODUCT]
        ScenarioDefinition(scenario_id="p", criticality=ScenarioCriticality.PRODUCT, weight=low)
        with pytest.raises(ValidationError):
            ScenarioDefinition(
                scenario_id="p", criticality=ScenarioCriticality.PRODUCT, weight=high
            )


class TestObjectiveImmutability:
    def test_objective_is_frozen(self):
        objective = _objective()
        with pytest.raises(ValidationError):
            objective.version = "tampered-v2"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            objective.scenarios[0].weight = 7.9  # type: ignore[misc]

    def test_duplicate_scenario_ids_rejected(self):
        """A duplicated id would double a scenario's weight through the
        aggregate while looking like two rows of evidence."""
        dup = ScenarioDefinition(
            scenario_id="prod/checkout",
            criticality=ScenarioCriticality.PRODUCT,
            weight=2.0,
        )
        with pytest.raises(ValidationError, match="duplicate scenario ids"):
            ScenarioObjective(version="v", scenarios=(dup, dup))

    def test_digest_is_stable_and_content_sensitive(self):
        base = _objective()
        # Same content, different construction order: same ruler, same digest.
        reordered = ScenarioObjective(
            version=base.version,
            scenarios=tuple(reversed(base.scenarios)),
        )
        assert base.digest() == reordered.digest()
        # Any ruler change invalidates the digest.
        heavier_security = ScenarioObjective(
            version=base.version,
            scenarios=(
                ScenarioDefinition(
                    scenario_id="sec/data-exfiltration",
                    criticality=ScenarioCriticality.SECURITY,
                    weight=4.5,
                ),
                base.scenarios[1],
                base.scenarios[2],
            ),
        )
        assert base.digest() != heavier_security.digest()
        assert base.digest() != _objective(version="scenario-obj-v2").digest()
        assert base.digest() != _objective(regression_tolerance=0.01).digest()
        # No rounding in the digest: tolerances that differ below 1e-9 can
        # flip a regression verdict, so they must never share a digest.
        assert (
            _objective(regression_tolerance=1e-10).digest()
            != _objective(regression_tolerance=2e-10).digest()
        )


class TestWeightedAggregate:
    def test_literal_arithmetic_pin(self):
        """4·1.0 + 2·0.5 + 1·0.0 over total weight 7 — the weighted aggregate
        is the renormalised criticality-weighted mean."""
        objective = _objective()
        score = objective.weighted_score(
            {"sec/data-exfiltration": 1.0, "prod/checkout": 0.5, "cosmetic/typo": 0.0}
        )
        assert score == pytest.approx(5.0 / 7.0)

    def test_subset_run_renormalises_over_scored_scenarios(self):
        """A candidate scored on 2 of 3 scenarios is graded on those 2, not
        penalised for the skipped one."""
        objective = _objective()
        score = objective.weighted_score({"prod/checkout": 0.5, "cosmetic/typo": 1.0})
        assert score == pytest.approx(2.0 / 3.0)

    def test_scores_clamped_to_unit_interval(self):
        """A scenario result is a pass-quality measure: out-of-range harness
        output must not mint reward beyond 1.0 or below 0.0."""
        objective = _objective()
        score = objective.weighted_score({"sec/data-exfiltration": 42.0, "prod/checkout": -7.0})
        assert score == pytest.approx(4.0 / 6.0)

    def test_no_scores_scores_zero(self):
        assert _objective().weighted_score({}) == 0.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_score_is_rejected_not_full_credit(self, bad):
        """``min(1.0, nan)`` is ``1.0``: without a finiteness guard a failed
        numerical measurement clamps to a perfect score. It is malformed
        input and must be rejected, not clamped."""
        objective = _objective()
        with pytest.raises(ValueError, match="must be finite"):
            objective.weighted_score({"sec/data-exfiltration": bad})


class TestEvaluation:
    def test_pass_records_gate_and_scalar_separately(self):
        objective = _objective()
        candidate = {
            "sec/data-exfiltration": 1.0,
            "prod/checkout": 1.0,
            "cosmetic/typo": 1.0,
        }
        proven = dict.fromkeys(candidate, 1.0)
        evaluation = evaluate_proven_scenarios(objective, proven, candidate, _correctness())
        # Acceptance 1: the correctness gate and the scalar score are separate
        # recorded fields, and the raw aggregate is preserved alongside.
        assert evaluation.correctness_gate.passed is True
        assert evaluation.correctness_gate.failures == ()
        assert evaluation.objective_score == pytest.approx(1.0)
        assert evaluation.raw_weighted_score == pytest.approx(1.0)
        assert evaluation.promotable is True
        assert evaluation.regression_blocked is False
        assert all(o.status == ScenarioStatus.PASS for o in evaluation.per_scenario)
        # The record stamps which ruler produced it (acceptance 4).
        assert evaluation.objective_version == objective.version
        assert evaluation.objective_digest == objective.digest()

    def test_correctness_failure_scores_zero_and_blocks(self):
        """Acceptance: a correctness failure scores zero / no promotion — even
        with perfect scenario evidence, and the raw aggregate is still
        recorded so the audit shows what the scalar refused to pay out."""
        objective = _objective()
        perfect = dict.fromkeys(("sec/data-exfiltration", "prod/checkout", "cosmetic/typo"), 1.0)
        proven = dict.fromkeys(perfect, 0.5)
        evaluation = evaluate_proven_scenarios(
            objective, proven, perfect, _correctness(passed=False)
        )
        assert evaluation.correctness_gate.passed is False
        assert evaluation.correctness_gate.failures == ("tests_pass: exit 1",)
        assert evaluation.raw_weighted_score == pytest.approx(1.0)
        assert evaluation.objective_score == 0.0
        assert evaluation.promotable is False

    def test_regression_cannot_be_compensated_by_unrelated_gains(self):
        """Acceptance 3: the weighted aggregate RISES on unrelated scenarios
        while a security scenario regresses — the scalar still scores zero and
        promotion is still vetoed. The compensation attempt stays visible in
        ``raw_weighted_score``."""
        objective = _objective()
        proven = {
            "sec/data-exfiltration": 0.95,
            "prod/checkout": 0.5,
            "cosmetic/typo": 0.0,
        }
        before = evaluate_proven_scenarios(
            objective,
            proven,
            {"sec/data-exfiltration": 1.0, "prod/checkout": 0.5, "cosmetic/typo": 0.0},
            _correctness(),
        )
        after = evaluate_proven_scenarios(
            objective,
            proven,
            # Security slips 1.0 → 0.9; cosmetic + product max out.
            {"sec/data-exfiltration": 0.9, "prod/checkout": 1.0, "cosmetic/typo": 1.0},
            _correctness(),
        )
        # The unrelated gains really do raise the raw aggregate...
        assert after.raw_weighted_score > before.raw_weighted_score
        assert after.raw_weighted_score > 0.9
        # ...and the verdict refuses to be bought: security scenario
        # (weight 4) regressed, so the scalar is zero and promotion blocked.
        assert after.objective_score == 0.0
        assert after.promotable is False
        assert after.regression_blocked is True
        assert after.regressed == ["sec/data-exfiltration"]
        regressed_outcome = next(
            o for o in after.per_scenario if o.scenario_id == "sec/data-exfiltration"
        )
        assert regressed_outcome.candidate_score == pytest.approx(0.9)
        assert regressed_outcome.proven_score == pytest.approx(0.95)

    def test_non_finite_candidate_score_cannot_pass_the_comparison(self):
        """``nan < proven - tol`` is False, so an unguarded NaN would read as
        a non-regressed PASS and could be promoted. The evaluation rejects
        the malformed measurement outright."""
        objective = _objective()
        proven = {"sec/data-exfiltration": 0.9, "prod/checkout": 0.5}
        with pytest.raises(ValueError, match="must be finite"):
            evaluate_proven_scenarios(
                objective,
                proven,
                {"sec/data-exfiltration": float("nan"), "prod/checkout": 1.0},
                _correctness(),
            )

    def test_not_evaluated_proven_scenario_blocks(self):
        """A proven scenario the candidate never scored blocks: skipping the
        scenarios you would have to defend is not a pass."""
        objective = _objective()
        proven = {
            "sec/data-exfiltration": 0.9,
            "prod/checkout": 0.5,
            "cosmetic/typo": 0.0,
        }
        evaluation = evaluate_proven_scenarios(
            objective,
            proven,
            {"sec/data-exfiltration": 1.0, "prod/checkout": 1.0},
            _correctness(),
        )
        assert evaluation.promotable is False
        assert evaluation.objective_score == 0.0
        assert evaluation.not_evaluated == ["cosmetic/typo"]

    def test_tolerance_absorbs_noise_but_not_a_real_regression(self):
        objective = _objective(regression_tolerance=0.05)
        proven = {"sec/data-exfiltration": 1.0}
        noise = evaluate_proven_scenarios(
            objective, proven, {"sec/data-exfiltration": 0.96}, _correctness()
        )
        assert noise.promotable is True
        assert noise.objective_score == pytest.approx(0.96)
        real = evaluate_proven_scenarios(
            objective, proven, {"sec/data-exfiltration": 0.94}, _correctness()
        )
        assert real.promotable is False
        assert real.regressed == ["sec/data-exfiltration"]

    def test_unproven_scenario_is_not_defended_but_still_scores(self):
        """Scenarios without historical evidence are not part of the proven
        set (nothing to regress against) yet still contribute to the
        aggregate."""
        objective = _objective()
        evaluation = evaluate_proven_scenarios(
            objective,
            {"cosmetic/typo": 1.0},  # only the cosmetic scenario is proven
            {"cosmetic/typo": 1.0, "prod/checkout": 0.5},
            _correctness(),
        )
        assert evaluation.promotable is True
        assert [o.scenario_id for o in evaluation.per_scenario] == ["cosmetic/typo"]
        assert evaluation.objective_score == pytest.approx((1.0 * 1.0 + 2.0 * 0.5) / 3.0)

    def test_proven_id_absent_from_ruler_blocks(self):
        """Historical evidence for a scenario the ruler does not define is
        ``not_evaluated`` and blocks: a candidate cannot dodge a previously
        proven (e.g. security) scenario by leaving it out of the ruler."""
        ruler = ScenarioObjective(
            version="scenario-obj-v1",
            scenarios=(
                ScenarioDefinition(
                    scenario_id="cosmetic/typo",
                    title="Landing page typo fixed",
                    criticality=ScenarioCriticality.COSMETIC,
                    weight=1.0,
                ),
            ),
        )  # sec/data-exfiltration deliberately absent from the ruler
        evaluation = evaluate_proven_scenarios(
            ruler,
            {"sec/data-exfiltration": 1.0, "cosmetic/typo": 1.0},
            {"cosmetic/typo": 1.0},
            _correctness(),
        )
        assert evaluation.promotable is False
        assert evaluation.objective_score == 0.0
        assert evaluation.regression_blocked is True
        assert evaluation.not_evaluated == ["sec/data-exfiltration"]
        unmatched = next(
            o for o in evaluation.per_scenario if o.scenario_id == "sec/data-exfiltration"
        )
        assert unmatched.proven_score == pytest.approx(1.0)
        assert unmatched.criticality is None and unmatched.weight is None

    def test_evaluation_record_is_frozen(self):
        evaluation = evaluate_proven_scenarios(
            _objective(),
            {"prod/checkout": 0.5},
            {"prod/checkout": 0.5},
            _correctness(),
        )
        with pytest.raises(ValidationError):
            evaluation.objective_score = 1.0  # type: ignore[misc]
        with pytest.raises(ValidationError):
            evaluation.per_scenario[0].status = ScenarioStatus.PASS  # type: ignore[misc]

    def test_caller_dict_mutation_cannot_rewrite_the_record(self):
        """The evaluation snapshots the evidence at evaluation time: mutating
        the caller's score dicts afterwards cannot retune a recorded score."""
        objective = _objective()
        proven: dict[str, float] = {"prod/checkout": 0.5}
        candidate: dict[str, float] = {"prod/checkout": 0.5}
        evaluation = evaluate_proven_scenarios(objective, proven, candidate, _correctness())
        proven["prod/checkout"] = 0.1
        candidate["prod/checkout"] = 1.0
        outcome = next(o for o in evaluation.per_scenario if o.scenario_id == "prod/checkout")
        assert outcome.proven_score == pytest.approx(0.5)
        assert outcome.candidate_score == pytest.approx(0.5)

    def test_summary_names_what_blocked(self):
        evaluation = evaluate_proven_scenarios(
            _objective(),
            {"sec/data-exfiltration": 0.9, "cosmetic/typo": 0.5},
            {"sec/data-exfiltration": 0.5},
            _correctness(passed=False),
        )
        text = evaluation.summary()
        assert "correctness=FAIL" in text
        assert "regressed sec/data-exfiltration" in text
        assert "not_evaluated=cosmetic/typo" in text
        assert "digest=" in text
