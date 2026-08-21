from __future__ import annotations

from datetime import UTC, datetime

from maistro_evolve.fitness import (
    _FITNESS_WEIGHTS,
    _HARD_GATE_THRESHOLDS,
    _check_hard_gate,
    _cost_efficiency,
    _latency_efficiency,
    _weighted_eval_score,
    compute_fitness,
)
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(eval_scores=None, harness_params=None):
    return PipelineGenome(
        id="test-g1",
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


class TestHardGate:
    def test_empty_scores_fails(self):
        g = _genome()
        passed, failures = _check_hard_gate(g)
        assert not passed
        assert len(failures) > 0

    def test_all_scores_above_gate_passes(self):
        scores = {k: v + 0.1 for k, v in _HARD_GATE_THRESHOLDS.items()}
        g = _genome(eval_scores=scores)
        passed, failures = _check_hard_gate(g)
        assert passed
        assert failures == []

    def test_one_below_gate_fails(self):
        scores = {k: v + 0.1 for k, v in _HARD_GATE_THRESHOLDS.items()}
        scores["proxy_ifeval"] = 0.1
        g = _genome(eval_scores=scores)
        passed, failures = _check_hard_gate(g)
        assert not passed
        assert any("proxy_ifeval" in f for f in failures)

    def test_gate_thresholds_cover_every_registered_proxy_benchmark(self):
        """Derived from the registry, not hand-listed.

        The previous version asserted a hardcoded set of 8 including `osworld`,
        which cannot produce a score at all (`run_osworld` raises and is not
        registered). That made the enumeration look complete while gating a
        benchmark that never runs — and it would not have noticed a newly
        registered benchmark arriving with no threshold.
        """
        from maistro_evolve.benchmarks import PROXY_BENCHMARKS

        assert set(PROXY_BENCHMARKS) <= set(_HARD_GATE_THRESHOLDS)

    def test_unrunnable_osworld_is_not_gated(self):
        """Both spellings: the registry uses `proxy_`-prefixed identifiers
        (SPEC-202), so asserting only the bare name would pass vacuously while
        a `proxy_osworld` entry sat in the threshold dict gating nothing."""
        from maistro_evolve.benchmarks import PROXY_BENCHMARKS

        for name in ("osworld", "proxy_osworld"):
            assert name not in PROXY_BENCHMARKS
            assert name not in _HARD_GATE_THRESHOLDS

    def test_benchmark_without_a_tuned_threshold_still_gets_gated(self):
        """The fail-open hole: the gate used to iterate the threshold dict and
        test `if bench in scores`, so any benchmark absent from that dict passed
        unconditionally — including `code_rsi`, the only one the RSI loop scores.
        """
        passed, failures = _check_hard_gate(_genome(eval_scores={"code_rsi": 0.0}))
        assert not passed
        assert any("code_rsi" in f and "default floor" in f for f in failures)

    def test_rejected_rsi_fix_cannot_breed(self):
        """`code_rsi` collapses to exactly 0.0 when the fix is rejected or the
        test signal is stubbed. Such a genome used to pass the gate and compete
        on cost/latency/diversity alone."""
        genome = _genome(eval_scores={"code_rsi": 0.0})
        assert compute_fitness(genome, [genome]).total == 0.0

    def test_a_real_rsi_score_still_passes(self):
        """Fail-closed must not mean fail-always: a subset run scoring one
        genuine benchmark still breeds."""
        passed, failures = _check_hard_gate(_genome(eval_scores={"code_rsi": 0.636}))
        assert passed and failures == []

    def test_subset_runs_are_not_penalised_for_skipped_benchmarks(self):
        """The property the old implementation got right, preserved."""
        passed, failures = _check_hard_gate(_genome(eval_scores={"ifeval": 0.9}))
        assert passed and failures == []


class TestWeightedEvalScore:
    def test_empty_scores_returns_zero(self):
        g = _genome()
        assert _weighted_eval_score(g) == 0.0

    def test_all_ones(self):
        scores = dict.fromkeys(EvalWeights.model_fields, 1.0)
        g = _genome(eval_scores=scores)
        assert abs(_weighted_eval_score(g) - 1.0) < 0.001

    def test_all_zeros(self):
        scores = dict.fromkeys(EvalWeights.model_fields, 0.0)
        g = _genome(eval_scores=scores)
        assert _weighted_eval_score(g) == 0.0

    def test_partial_scores(self):
        scores = {"proxy_ifeval": 0.8, "proxy_bfcl": 0.6}
        g = _genome(eval_scores=scores)
        score = _weighted_eval_score(g)
        assert 0.0 < score < 1.0


class TestCostEfficiency:
    def test_zero_cost(self):
        g = _genome(harness_params={})
        assert _cost_efficiency(g) == 1.0

    def test_high_cost(self):
        g = _genome(harness_params={"total_cost_usd": 10.0})
        eff = _cost_efficiency(g)
        assert 0.0 < eff < 1.0

    def test_inversely_proportional(self):
        g1 = _genome(harness_params={"total_cost_usd": 1.0})
        g2 = _genome(harness_params={"total_cost_usd": 5.0})
        assert _cost_efficiency(g1) > _cost_efficiency(g2)


class TestLatencyEfficiency:
    def test_zero_latency(self):
        g = _genome(harness_params={})
        assert _latency_efficiency(g) == 1.0

    def test_inversely_proportional(self):
        g1 = _genome(harness_params={"avg_latency_seconds": 1.0})
        g2 = _genome(harness_params={"avg_latency_seconds": 10.0})
        assert _latency_efficiency(g1) > _latency_efficiency(g2)


class TestComputeFitness:
    def test_failed_hard_gate_zero_fitness(self):
        g = _genome(eval_scores={"proxy_ifeval": 0.1})
        fitness = compute_fitness(g, [g])
        assert fitness.total == 0.0
        assert not fitness.passed_hard_gate

    def test_passed_hard_gate_nonzero_fitness(self):
        scores = {k: v + 0.2 for k, v in _HARD_GATE_THRESHOLDS.items()}
        g = _genome(eval_scores=scores)
        fitness = compute_fitness(g, [g])
        assert fitness.passed_hard_gate
        assert fitness.total > 0.0

    def test_fitness_weights_sum_to_one(self):
        total = sum(_FITNESS_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_higher_eval_scores_higher_fitness(self):
        scores_low = {k: v + 0.05 for k, v in _HARD_GATE_THRESHOLDS.items()}
        scores_high = dict.fromkeys(_HARD_GATE_THRESHOLDS, 0.9)
        g_low = _genome(eval_scores=scores_low)
        g_high = _genome(eval_scores=scores_high)
        f_low = compute_fitness(g_low, [g_low])
        f_high = compute_fitness(g_high, [g_high])
        assert f_high.total > f_low.total

    def test_elo_bonus_increases_fitness(self):
        scores = dict.fromkeys(_HARD_GATE_THRESHOLDS, 0.8)
        g_no_elo = _genome(eval_scores=scores, harness_params={})
        g_with_elo = _genome(eval_scores=scores, harness_params={"avg_elo": 1400.0})
        f_no = compute_fitness(g_no_elo, [g_no_elo])
        f_yes = compute_fitness(g_with_elo, [g_with_elo])
        assert f_yes.total > f_no.total

    def test_diversity_bonus_zero_when_population_has_no_other_genomes(self):
        # population length is >= 2 but every entry shares the genome's own
        # id, so the "other.id != genome.id" filter leaves distances empty.
        scores = dict.fromkeys(_HARD_GATE_THRESHOLDS, 0.8)
        g = _genome(eval_scores=scores)
        fitness = compute_fitness(g, [g, g])
        assert fitness.diversity_bonus == 0.0

    def test_diversity_bonus_positive_when_population_has_a_distinct_genome(self):
        scores = dict.fromkeys(_HARD_GATE_THRESHOLDS, 0.8)
        g = _genome(eval_scores=scores)
        other = _genome(eval_scores=scores)
        other.id = "test-g2"
        other.topology.nodes[0].temperature = 0.9
        fitness = compute_fitness(g, [g, other])
        assert fitness.diversity_bonus > 0.0
