"""#853 — fitness is population-owned, missing-data-pessimistic, capability-grounded.

These tests pin the *ruler*, not just a score: the objective lives outside the
genome, absence of a measurement is never an ideal measurement, correctness
gates are non-tradeable constraints, Elo/diversity are role-separated context
terms, and identical evidence recomputes bit-identical fitness across cycles.

The arithmetic pins use literal expected values so a materially wrong
aggregation mutation (swapped weights, restored missing→1.0 freebies, removed
gate, renormalisation drift) cannot pass by dragging its own expectation along.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maistro_evolve.fitness import (
    _HARD_GATE_THRESHOLDS,
    COMPONENT_ROLES,
    _check_hard_gate,
    _elo_bonus,
    _weighted_eval_score,
    compute_fitness,
)
from maistro_evolve.objective import (
    DEFAULT_OBJECTIVE,
    EvaluationObjective,
    FitnessTermWeights,
)
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(
    genome_id: str = "g1",
    eval_scores: dict[str, float] | None = None,
    harness_params: dict | None = None,
) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name="test",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        eval_scores=eval_scores or {},
        harness_params=harness_params or {},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


class TestObjectiveOwnership:
    def test_genome_cannot_reweight_its_own_score(self):
        """The core #853 defect: two genomes with identical measured evidence
        but radically different self-carried weight vectors must score
        identically — the ruler is not the candidate's."""
        scores = {"proxy_ifeval": 0.9, "proxy_bfcl": 0.3}
        humble = _genome("humble", eval_scores=scores, harness_params={})
        # The old attack: crank the weights of the benchmarks you score well on.
        # EvalWeights no longer influences scoring at all, so the attack is dead.
        gamed = _genome("gamed", eval_scores=scores, harness_params={})
        gamed.eval_weights = EvalWeights(
            proxy_ifeval=0.9,
            proxy_bfcl=0.01,
            proxy_swebench=0.01,
            proxy_terminalbench=0.01,
            proxy_tau_bench=0.01,
            proxy_gaia=0.01,
            proxy_ragas=0.01,
            ifeval=0.01,
            bfcl=0.01,
        )
        pop = [humble, gamed]
        f_humble = compute_fitness(humble, pop)
        f_gamed = compute_fitness(gamed, pop)
        assert f_humble.weighted_eval_score == pytest.approx(f_gamed.weighted_eval_score)
        assert f_humble.total == pytest.approx(f_gamed.total)

    def test_weighted_eval_score_uses_objective_not_genome_weights(self):
        g = _genome(eval_scores={"proxy_ifeval": 0.8, "proxy_bfcl": 0.6})
        # Default objective: both weighted 0.15 → renormalised mean 0.7.
        assert _weighted_eval_score(g, DEFAULT_OBJECTIVE) == pytest.approx(0.70)
        # A deliberately different population objective changes the number —
        # but only via the objective, never via the genome's own field.
        strict = EvaluationObjective(
            version="strict-v1",
            benchmark_weights={"proxy_ifeval": 1.0, "proxy_bfcl": 0.0},
            default_benchmark_weight=0.15,
            fitness_term_weights=FitnessTermWeights(),
        )
        assert _weighted_eval_score(g, strict) == pytest.approx(0.80)

    def test_unlisted_benchmark_gets_the_default_objective_weight(self):
        # code_rsi is not named in the objective: a subset RSI run still yields
        # a real score (0.15 / 0.15 renormalised to 1.0).
        g = _genome(eval_scores={"code_rsi": 0.636})
        assert _weighted_eval_score(g, DEFAULT_OBJECTIVE) == pytest.approx(0.636)

    def test_objective_is_frozen_and_snapshots_its_weight_dict(self):
        weights = {"proxy_ifeval": 0.5}
        obj = EvaluationObjective(
            version="t",
            benchmark_weights=weights,
            default_benchmark_weight=0.15,
            fitness_term_weights=FitnessTermWeights(),
        )
        # A caller mutating the dict it passed in must not retune the objective.
        weights["proxy_ifeval"] = 999.0
        assert obj.benchmark_weights["proxy_ifeval"] == 0.5
        # Field reassignment is refused.
        with pytest.raises(ValidationError):
            obj.version = "mutated"
        with pytest.raises(ValidationError):
            obj.default_benchmark_weight = 42.0

    def test_mutation_operators_no_longer_carry_the_ruler(self):
        import maistro_evolve.mutate as mutate

        parent = _genome()
        parent.eval_weights = EvalWeights(proxy_ifeval=0.42)
        child = mutate.mutate_all(parent, rate=1.0)
        assert child.eval_weights == parent.eval_weights

    def test_cycle_scores_the_whole_population_with_one_objective(self):
        """Campaign ownership: the EvolutionCycle holds the objective and every
        genome in `_compute_all_fitness` is scored under it."""
        from maistro_evolve.cycle import EvolutionCycle
        from maistro_evolve.population import PopulationStore

        obj = EvaluationObjective(
            version="campaign-v9",
            benchmark_weights=dict(DEFAULT_OBJECTIVE.benchmark_weights),
            default_benchmark_weight=0.15,
            fitness_term_weights=FitnessTermWeights(),
        )
        cycle = EvolutionCycle(objective=obj)
        assert cycle.objective.version == "campaign-v9"
        store = PopulationStore()
        a = _genome("a", eval_scores={"proxy_ifeval": 0.8})
        b = _genome("b", eval_scores={"proxy_ifeval": 0.5})
        store.add(a)
        store.add(b)
        cycle._compute_all_fitness(store)
        direct = compute_fitness(a, [a, b], obj)
        assert store.get("a").fitness_score == pytest.approx(direct.total)


class TestMissingDataPessimism:
    def test_missing_cost_and_latency_score_zero_not_full_marks(self):
        """The audited defect: a do-nothing genome with unrecorded cost and
        latency used to collect 0.15 + 0.10 of the composite for free. It must
        now collect the missing-evidence credit (0.0) on both terms."""
        g = _genome(eval_scores={"proxy_ifeval": 0.5, "proxy_bfcl": 0.5})
        components = compute_fitness(g, [g])
        # w_eval = 0.5; only the eval term is funded (cost/latency missing).
        expected = 0.5 * 0.65 * 100.0
        assert components.total == pytest.approx(expected)
        assert components.cost_efficiency is None
        assert components.latency_efficiency is None
        assert set(components.missing_evidence) == {
            "cost_efficiency",
            "latency_efficiency",
            "elo_bonus",
        }

    def test_measured_expensive_work_outranks_unrecorded_work(self):
        """Absence is never an ideal zero-cost observation: a measured
        expensive candidate must outscore an identical candidate whose cost was
        simply never written down."""
        scores = {"proxy_ifeval": 0.6, "proxy_bfcl": 0.6}
        measured = _genome(
            "measured",
            eval_scores=scores,
            harness_params={"total_cost_usd": 5.0, "avg_latency_seconds": 10.0},
        )
        unrecorded = _genome("unrecorded", eval_scores=scores)
        pop = [measured, unrecorded]
        assert compute_fitness(measured, pop).total > compute_fitness(unrecorded, pop).total

    def test_missing_elo_is_not_a_default_elo_award(self):
        """A never-battled genome (whose Elo tournament would report the 1200
        default) earns 0.0 on the Elo term — no head-to-head evidence, no
        credit, no free half-strength bonus for existing."""
        scores = {"proxy_ifeval": 0.8, "proxy_bfcl": 0.8}
        no_evidence = _genome("a", eval_scores=scores)
        battled = _genome(
            "b", eval_scores=scores, harness_params={"avg_elo": 1200.0, "elo_battles": 4}
        )
        f_none = compute_fitness(no_evidence, [no_evidence])
        f_default_elo = compute_fitness(battled, [battled])
        # Both map a 1200 average to (1200-1000)/400 = 0.5 — but only one of
        # them ever fought a battle to earn it.
        assert f_none.elo_bonus is None
        assert f_default_elo.elo_bonus == pytest.approx(0.5)
        assert f_default_elo.total > f_none.total


class TestDegenerateAndMalformedEvidence:
    """Boundary pins for evidence that exists but is worthless (#853).

    Missing-data pessimism must survive not just *absent* evidence but
    present-and-garbage evidence: a malformed number must never crash the
    scorer into a freebie (or out of one) — it is unknown, like absence.
    """

    def test_zero_avg_elo_with_battle_count_is_unknown_not_awarded(self):
        # Battles recorded but avg_elo <= 0 is inconsistent evidence: the Elo
        # mapping would clamp it to 0.0 anyway, but the policy is stronger —
        # non-positive Elo is not a measurement, it is the missing sentinel.
        g = _genome(
            "g",
            eval_scores={"proxy_ifeval": 0.8},
            harness_params={"avg_elo": 0.0, "elo_battles": 3},
        )
        assert _elo_bonus(g) is None

    def test_elo_band_boundaries(self):
        # The [1000, 1400] band maps to [0.0, 1.0], inclusive at both ends.
        at_floor = _genome(
            "g",
            eval_scores={"proxy_ifeval": 0.8},
            harness_params={"avg_elo": 1000.0, "elo_battles": 1},
        )
        at_ceiling = _genome(
            "g",
            eval_scores={"proxy_ifeval": 0.8},
            harness_params={"avg_elo": 1400.0, "elo_battles": 1},
        )
        beyond = _genome(
            "g",
            eval_scores={"proxy_ifeval": 0.8},
            harness_params={"avg_elo": 2000.0, "elo_battles": 1},
        )
        assert _elo_bonus(at_floor) == 0.0
        assert _elo_bonus(at_ceiling) == 1.0
        assert _elo_bonus(beyond) == 1.0  # clamped, never superlinear

    @pytest.mark.parametrize("field", ["total_cost_usd", "avg_latency_seconds", "avg_elo"])
    def test_non_numeric_evidence_is_unknown_not_crash_or_freebie(self, field):
        # Garbage in the evidence field must not crash compute_fitness and
        # must not read as a measured value: the term scores missing credit.
        g = _genome(
            "g",
            eval_scores={"proxy_ifeval": 0.8},
            harness_params={field: "not-a-number"},
        )
        components = compute_fitness(g, [g])
        assert components.cost_efficiency is None
        assert components.latency_efficiency is None
        assert components.elo_bonus is None
        assert components.total == pytest.approx(0.8 * 0.65 * 100.0)


class TestHardGatesAreNonTradeable:
    def test_gate_failure_zeroes_fitness_under_any_objective_and_context(self):
        scores = {"proxy_ifeval": 0.1}  # below the 0.25 gate
        g = _genome(
            "weak", eval_scores=scores, harness_params={"avg_elo": 1400.0, "elo_battles": 40}
        )
        peer = _genome("peer", eval_scores={"proxy_ifeval": 0.9})
        peer.topology.nodes[0].temperature = 0.95
        generous = EvaluationObjective(
            version="generous-v1",
            benchmark_weights={"proxy_ifeval": 1.0},
            default_benchmark_weight=0.15,
            fitness_term_weights=FitnessTermWeights(
                eval_score=0.05,
                cost_efficiency=0.25,
                latency_efficiency=0.25,
                diversity_bonus=0.25,
                elo_bonus=0.20,
            ),
        )
        for objective in (DEFAULT_OBJECTIVE, generous):
            components = compute_fitness(g, [g, peer], objective)
            assert components.total == 0.0
            assert components.capability_score == 0.0
            assert not components.passed_hard_gate

    def test_gate_boundary_is_inclusive(self):
        # Exactly at the threshold passes (score < threshold fails).
        at_gate = dict(_HARD_GATE_THRESHOLDS)
        passed, failures = _check_hard_gate(_genome(eval_scores=at_gate))
        assert passed and failures == []

    def test_capability_score_equals_gated_measured_quality(self):
        good = _genome("good", eval_scores={"proxy_ifeval": 0.9})
        bad = _genome("bad", eval_scores={"proxy_ifeval": 0.1})
        f_good = compute_fitness(good, [good])
        f_bad = compute_fitness(bad, [bad])
        assert f_good.capability_score == pytest.approx(f_good.weighted_eval_score)
        assert f_bad.capability_score == 0.0


class TestSemanticRoleSeparation:
    def test_context_roles_are_disjoint_from_measured_roles(self):
        measured = {name for name, role in COMPONENT_ROLES.items() if role.startswith("measured")}
        context = {name for name, role in COMPONENT_ROLES.items() if role.endswith("_context")}
        assert measured and context
        assert measured.isdisjoint(context)
        # The capability score is measured, never context.
        assert COMPONENT_ROLES["capability_score"].startswith("measured")
        assert "diversity_bonus" in context
        assert "elo_bonus" in context

    def test_components_carry_their_roles(self):
        g = _genome(eval_scores={"proxy_ifeval": 0.8})
        components = compute_fitness(g, [g])
        assert components.component_roles["elo_bonus"] == "head_to_head_context"
        assert components.component_roles["capability_score"] == ("measured_task_quality_gated")


class TestDeterministicRecomputation:
    def test_identical_evidence_recomputes_identical_fitness(self):
        """AC5/AC8: same evidence → same total, same hash — across calls and
        across simulated cycles. Fitness cannot creep upward on unchanged
        evidence."""
        g = _genome(
            eval_scores={"proxy_ifeval": 0.7, "proxy_bfcl": 0.55},
            harness_params={"total_cost_usd": 1.5, "avg_latency_seconds": 2.0},
        )
        peer = _genome("peer", eval_scores={"proxy_ifeval": 0.4})
        pop = [g, peer]

        first = compute_fitness(g, pop)
        for _ in range(3):  # "later cycles" with zero evidence change
            again = compute_fitness(g, list(reversed(pop)))
            assert again.total == first.total
            assert again.evidence_hash == first.evidence_hash

    def test_population_list_order_cannot_change_the_score(self):
        g = _genome("g", eval_scores={"proxy_ifeval": 0.7})
        peers = [
            _genome("p1", eval_scores={"proxy_ifeval": 0.4}),
            _genome("p2", eval_scores={"proxy_ifeval": 0.5}),
            _genome("p3", eval_scores={"proxy_ifeval": 0.6}),
        ]
        forward = compute_fitness(g, [g, *peers])
        backward = compute_fitness(g, [g, *reversed(peers)])
        assert forward.total == backward.total
        assert forward.evidence_hash == backward.evidence_hash

    def test_any_evidence_or_objective_change_is_visible_in_the_hash(self):
        base = _genome("g", eval_scores={"proxy_ifeval": 0.7})
        peer = _genome("p", eval_scores={"proxy_ifeval": 0.4})
        baseline = compute_fitness(base, [base, peer])

        re_eLOd = _genome(
            "g",
            eval_scores={"proxy_ifeval": 0.7},
            harness_params={"avg_elo": 1250.0, "elo_battles": 6},
        )
        assert compute_fitness(re_eLOd, [re_eLOd, peer]).evidence_hash != (baseline.evidence_hash)

        re_scored = _genome("g", eval_scores={"proxy_ifeval": 0.71})
        assert compute_fitness(re_scored, [re_scored, peer]).evidence_hash != (
            baseline.evidence_hash
        )

        grew = _genome("g", eval_scores={"proxy_ifeval": 0.7})
        grew.topology.max_cycles = 9  # diversity-relevant trait evidence
        assert compute_fitness(grew, [grew, peer]).evidence_hash != (baseline.evidence_hash)

        assert DEFAULT_OBJECTIVE.version != "unversioned"
        components = compute_fitness(base, [base, peer])
        assert components.objective_version == DEFAULT_OBJECTIVE.version
        assert len(components.evidence_hash) == 64  # sha256 hexdigest


class TestArithmeticPins:
    """Literal calibration — kills materially wrong aggregation mutations."""

    def _scored(self) -> PipelineGenome:
        return _genome(
            eval_scores={"proxy_ifeval": 0.8, "proxy_bfcl": 0.6},
            harness_params={"total_cost_usd": 1.0, "avg_latency_seconds": 3.0},
        )

    def test_total_calibration_with_measured_cost_and_latency(self):
        # w_eval = (0.15*0.8 + 0.15*0.6) / 0.30 = 0.70
        # cost_eff = 1/(1+1) = 0.5; lat_eff = 1/(1+3) = 0.25
        # no peers → diversity 0; no battle evidence → elo credit 0
        # total = (0.70*0.65 + 0.5*0.15 + 0.25*0.10) * 100 = 55.5
        g = self._scored()
        assert compute_fitness(g, [g]).total == pytest.approx(55.5)

    def test_swapped_cost_latency_weights_are_killed_by_the_pin(self):
        # A 0.15 <-> 0.10 swap would give 0.455 + 0.05 + 0.0375 → 54.25.
        g = self._scored()
        total = compute_fitness(g, [g]).total
        assert total != pytest.approx(54.25)

    def test_restored_missing_freebies_are_killed_by_the_pin(self):
        # The pre-#853 behaviour (missing cost/latency → 1.0 each) would score
        # this evidence at (0.455 + 0.15 + 0.10) * 100 = 70.5.
        g = _genome(eval_scores={"proxy_ifeval": 0.8, "proxy_bfcl": 0.6})
        total = compute_fitness(g, [g]).total
        assert total == pytest.approx(0.70 * 0.65 * 100.0)
        assert total != pytest.approx(70.5)

    def test_reinstated_default_elo_award_is_killed(self):
        # Writing the never-battled 1200 default as evidence would add
        # 0.5*0.05*100 = 2.5 to the total.
        g = _genome(eval_scores={"proxy_ifeval": 0.8, "proxy_bfcl": 0.6})
        total = compute_fitness(g, [g]).total
        assert total != pytest.approx(0.70 * 0.65 * 100.0 + 2.5)

    def test_removed_gate_is_killed(self):
        # Without the hard gate this below-gate genome would still score
        # (0.1-weighted eval term); with it, exactly zero.
        g = _genome(eval_scores={"proxy_ifeval": 0.1})
        assert compute_fitness(g, [g]).total == 0.0

    def test_do_nothing_candidate_scores_zero_and_records_missing_evidence(self):
        """AC7, scoring side: a candidate whose every function body is disabled
        produces no benchmark evidence — total 0.0, gate failed, every soft
        term explicitly missing, no reweighting in sight."""
        noop = _genome()  # no eval_scores, no harness evidence at all
        peer = _genome("peer", eval_scores={"proxy_ifeval": 0.9})
        peer.topology.nodes[0].temperature = 0.99
        components = compute_fitness(noop, [noop, peer])
        assert components.total == 0.0
        assert components.capability_score == 0.0
        assert not components.passed_hard_gate
        assert components.gate_failures == ["no benchmarks evaluated"]
        assert set(components.missing_evidence) == {
            "cost_efficiency",
            "latency_efficiency",
            "elo_bonus",
        }


class TestTenureFreebieIsGone:
    def test_rebattled_but_not_improved_genome_gains_no_capability(self):
        """AC4/AC8: re-battling across cycles updates Elo *evidence* (a recorded
        change, hash-visible) but can never move capability."""
        scores = {"proxy_ifeval": 0.6, "proxy_bfcl": 0.6}
        cycle1 = _genome(
            "g", eval_scores=scores, harness_params={"avg_elo": 1200.0, "elo_battles": 2}
        )
        cycle5 = _genome(
            "g", eval_scores=scores, harness_params={"avg_elo": 1232.0, "elo_battles": 30}
        )
        peer = _genome("peer", eval_scores={"proxy_ifeval": 0.5})
        f1 = compute_fitness(cycle1, [cycle1, peer])
        f5 = compute_fitness(cycle5, [cycle5, peer])
        # Re-battling churned the evidence (hash moved — the recorded reason),
        # but measured task quality is bit-identical.
        assert f5.capability_score == pytest.approx(f1.capability_score)
        assert f5.evidence_hash != f1.evidence_hash
        # And the bounded context share caps the total gain at 5% of fitness.
        assert f5.total - f1.total <= 5.0 + 1e-9
