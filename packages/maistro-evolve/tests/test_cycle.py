from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.cycle import (
    EvolutionConfig,
    EvolutionCycle,
    FitnessEvidenceDriftError,
)
from maistro_evolve.fitness import compute_fitness
from maistro_evolve.harness import EvalHarness
from maistro_evolve.objective import (
    DEFAULT_OBJECTIVE,
    OBJECTIVE_VERSION,
    EvaluationObjective,
)
from maistro_evolve.population import PopulationStore
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalResult, EvalWeights, NodeGenome, PipelineGenome


def _fake_harness(names: list[str]) -> EvalHarness:
    """A harness registered with fast, deterministic fake runners (no real
    scoring, no llm_call requirement) — for exercising EvolutionCycle's own
    machinery (population growth, tournament, self-improve triggering)
    without needing a real model call or the real proxy benchmarks."""
    harness = EvalHarness()
    harness._benchmarks.clear()
    for name in names:

        async def fake_runner(
            genome: PipelineGenome, llm_call: object, _name: str = name
        ) -> EvalResult:
            return EvalResult(
                benchmark=_name,
                score=0.5,
                cost_usd=0.0,
                duration_seconds=0.0,
                samples_evaluated=1,
                metadata={"fidelity": "proxy"},
            )

        harness.register_benchmark(name, fake_runner)
    return harness


def _genome(name="test"):
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
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
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


class TestPopulationStore:
    def test_add_and_get(self):
        store = PopulationStore()
        g = _genome("a")
        store.add(g)
        assert store.get("g-a") is not None
        assert store.get("g-a").id == "g-a"

    def test_get_missing_returns_none(self):
        store = PopulationStore()
        assert store.get("nonexistent") is None

    def test_list_all(self):
        store = PopulationStore()
        store.add(_genome("a"))
        store.add(_genome("b"))
        assert len(store.list_all()) == 2

    def test_remove(self):
        store = PopulationStore()
        store.add(_genome("a"))
        store.remove("g-a")
        assert store.get("g-a") is None

    def test_get_champion_none_when_empty(self):
        store = PopulationStore()
        assert store.get_champion() is None

    def test_get_champion_returns_highest_fitness(self):
        store = PopulationStore()
        g1 = _genome("a")
        g1.fitness_score = 50.0
        g1.eval_scores = {"proxy_ifeval": 0.8, "proxy_bfcl": 0.7}
        g2 = _genome("b")
        g2.fitness_score = 80.0
        g2.eval_scores = {"proxy_ifeval": 0.9, "proxy_bfcl": 0.8}
        for g in (g1, g2):
            # Governed-selection evidence (#854): repeated samples, stable
            # spread, objective-stamped, current.
            g.harness_params["eval_samples"] = dict.fromkeys(g.eval_scores, 2)
            g.harness_params["eval_history"] = {
                b: [s - 0.01, s + 0.01] for b, s in g.eval_scores.items()
            }
            g.harness_params["objective_version"] = "objective-test"
            g.harness_params["evidence_cycle"] = 1
        store.add(g1)
        store.add(g2)
        champ = store.get_champion()
        assert champ is not None
        assert champ.id == "g-b"

    def test_get_champion_none_when_nothing_eligible(self):
        """Scores alone no longer make a champion: a single lucky sample per
        benchmark is insufficient independent evidence under the #854 policy,
        so there is NO champion rather than an unevaluable one."""
        store = PopulationStore()
        g = _genome("a")
        g.fitness_score = 90.0
        g.eval_scores = {"proxy_ifeval": 0.99}
        g.harness_params["eval_samples"] = {"proxy_ifeval": 1}
        store.add(g)
        assert store.get_champion() is None

    def test_cull_bottom_removes_lowest(self):
        store = PopulationStore()
        for i in range(10):
            g = _genome(str(i))
            g.fitness_score = float(i) * 10
            store.add(g)
        removed = store.cull_bottom(0.3)
        assert removed == 3
        remaining = store.list_all()
        assert len(remaining) == 7
        assert all(g.fitness_score >= 30.0 for g in remaining)

    def test_get_breeding_pool(self):
        store = PopulationStore()
        for i in range(10):
            g = _genome(str(i))
            g.fitness_score = float(i) * 10
            store.add(g)
        pool = store.get_breeding_pool(3)
        assert len(pool) == 3
        assert pool[0].fitness_score >= pool[1].fitness_score

    def test_lineage_follows_parents(self):
        store = PopulationStore()
        g1 = _genome("a")
        g2 = _genome("b")
        g3 = _genome("c")
        g3.parent_a_id = "g-a"
        store.add(g1)
        store.add(g2)
        store.add(g3)
        lineage = store.get_lineage("g-c")
        assert len(lineage) == 2
        assert lineage[0].id == "g-c"
        assert lineage[1].id == "g-a"


class TestEvolutionCycle:
    @pytest.mark.asyncio
    async def test_cycle_creates_children(self):
        population = PopulationStore()
        for i in range(6):
            population.add(_genome(f"s{i}"))

        harness = _fake_harness(["proxy_ifeval", "proxy_bfcl"])
        tournament = EloTournament()
        config = EvolutionConfig(
            population_size=10,
            eval_batch_size=2,
            target_benchmarks=["proxy_ifeval", "proxy_bfcl"],
            self_improve=False,
        )

        cycle = EvolutionCycle(harness=harness, tournament=tournament)
        await cycle.run_cycle(population, llm_call=None, config=config)

        assert len(population.list_all()) >= 6

    @pytest.mark.asyncio
    async def test_cycle_populates_tournament(self):
        population = PopulationStore()
        for i in range(4):
            g = _genome(f"s{i}")
            g.eval_scores = {"proxy_ifeval": 0.5 + i * 0.1, "proxy_bfcl": 0.4 + i * 0.1}
            g.fitness_score = float(i) * 10
            population.add(g)

        harness = _fake_harness(["proxy_ifeval", "proxy_bfcl"])
        tournament = EloTournament()
        config = EvolutionConfig(
            population_size=6,
            target_benchmarks=["proxy_ifeval", "proxy_bfcl"],
            self_improve=False,
        )

        cycle = EvolutionCycle(harness=harness, tournament=tournament)
        await cycle.run_cycle(population, llm_call=None, config=config)

        stats = tournament.get_stats()
        assert stats["total_battles"] > 0

    @pytest.mark.asyncio
    async def test_cycle_with_self_improve(self):
        population = PopulationStore()
        g = _genome("top")
        g.eval_scores = {"proxy_ifeval": 0.8, "proxy_bfcl": 0.7, "proxy_gaia": 0.6}
        g.fitness_score = 60.0
        population.add(g)
        for i in range(3):
            population.add(_genome(f"fill{i}"))

        harness = _fake_harness(["proxy_ifeval", "proxy_bfcl", "proxy_gaia"])
        tournament = EloTournament()
        config = EvolutionConfig(
            population_size=5,
            target_benchmarks=["proxy_ifeval", "proxy_bfcl"],
            self_improve=True,
            self_improve_top_n=1,
        )

        cycle = EvolutionCycle(harness=harness, tournament=tournament)
        await cycle.run_cycle(population, llm_call=None, config=config)

        genomes = population.list_all()
        assert len(genomes) >= 4


class TestFitnessEvidenceLedger:
    """#853 AC5/AC8 enforced in production: the cycle keeps each genome's
    latest fitness evidence and refuses a score that moves although the
    evidence hash and objective version did not — recomputability is a
    runtime property of the loop, not a hope the tests hold on its behalf.
    """

    @staticmethod
    def _scored_population() -> PopulationStore:
        population = PopulationStore()
        a = _genome("a")
        a.eval_scores = {"proxy_ifeval": 0.8, "proxy_bfcl": 0.6}
        a.harness_params["total_cost_usd"] = 0.5
        population.add(a)
        b = _genome("b")
        b.eval_scores = {"proxy_ifeval": 0.4}
        b.topology.nodes[0].temperature = 0.9  # distinct trait evidence
        population.add(b)
        return population

    def test_identical_evidence_recomputes_identically_and_is_recorded(self):
        cycle = EvolutionCycle()
        pop = self._scored_population()
        expected = {
            g.id: compute_fitness(g, pop.list_all(), cycle.objective).total for g in pop.list_all()
        }

        # Two passes through the SAME cycle: the second sees the first's
        # record, finds the evidence unchanged, and must not raise.
        first = {g.id: g.fitness_score for g in cycle._compute_all_fitness(pop)}
        second = {g.id: g.fitness_score for g in cycle._compute_all_fitness(pop)}
        assert first == second == expected

        rec = cycle.fitness_evidence["g-a"]
        direct = compute_fitness(pop.get("g-a"), pop.list_all(), cycle.objective)
        assert rec.total == expected["g-a"]
        assert rec.capability_score == direct.capability_score
        assert rec.objective_version == direct.objective_version == OBJECTIVE_VERSION
        assert rec.evidence_hash == direct.evidence_hash
        assert rec.evidence_hash  # a sha256 over the exact inputs is recorded
        assert rec.component_roles == direct.component_roles
        # Cost evidence was recorded for g-a, so it is not "missing".
        assert "cost_efficiency" not in rec.missing_evidence

    def test_score_drift_under_unchanged_evidence_raises(self):
        cycle = EvolutionCycle()
        pop = self._scored_population()
        cycle._compute_all_fitness(pop)

        # Simulate the scoring arithmetic moving under identical evidence:
        # hash and objective_version stay equal, the total does not. This is
        # the "genome's own score changed without improved capability" defect
        # in its purest form, and the cycle must refuse it.
        rec = cycle.fitness_evidence["g-a"]
        cycle.fitness_evidence["g-a"] = rec.model_copy(update={"total": rec.total + 5.0})
        with pytest.raises(FitnessEvidenceDriftError, match="identical evidence"):
            cycle._compute_all_fitness(pop)

    def test_evidence_change_is_not_flagged_and_is_re_recorded(self):
        cycle = EvolutionCycle()
        pop = self._scored_population()
        cycle._compute_all_fitness(pop)
        old_hash = cycle.fitness_evidence["g-a"].evidence_hash

        g = pop.get("g-a")
        g.eval_scores["proxy_ifeval"] = 0.9  # a real, recorded evidence change
        pop.add(g)
        cycle._compute_all_fitness(pop)  # must not raise

        rec = cycle.fitness_evidence["g-a"]
        assert rec.evidence_hash != old_hash
        assert rec.capability_score > 0.0

    def test_objective_change_is_not_flagged_and_is_recorded(self):
        cycle = EvolutionCycle()
        pop = self._scored_population()
        cycle._compute_all_fitness(pop)

        # A governed objective swap moves hash + version — a recorded reason
        # for the score to move — so the guard must stay silent while the
        # new ruler is what the record now names.
        cycle.objective = EvaluationObjective(
            version="pop-owned-v3-test",
            benchmark_weights=DEFAULT_OBJECTIVE.benchmark_weights,
            default_benchmark_weight=DEFAULT_OBJECTIVE.default_benchmark_weight,
            fitness_term_weights=DEFAULT_OBJECTIVE.fitness_term_weights,
            missing_evidence_credit=DEFAULT_OBJECTIVE.missing_evidence_credit,
        )
        cycle._compute_all_fitness(pop)  # must not raise
        assert cycle.fitness_evidence["g-a"].objective_version == "pop-owned-v3-test"


class TestEvalHarness:
    def test_proxy_harness_registers_seven_benchmarks_not_osworld(self):
        harness = EvalHarness(benchmark_fidelity="proxy")
        assert len(harness._benchmarks) == 7
        for name in [
            "proxy_ifeval",
            "proxy_bfcl",
            "proxy_swebench",
            "proxy_terminalbench",
            "proxy_tau_bench",
            "proxy_gaia",
            "proxy_ragas",
        ]:
            assert name in harness._benchmarks
        assert "proxy_osworld" not in harness._benchmarks

    @pytest.mark.asyncio
    async def test_evaluate_genome_without_llm_call_raises(self):
        """No stub tier: evaluating a real proxy benchmark with no llm_call
        is a hard error, not a fabricated score."""
        harness = EvalHarness(benchmark_fidelity="proxy")
        g = _genome("eval")
        with pytest.raises(ValueError, match="requires an llm_call"):
            await harness.evaluate_genome(g, benchmarks=["proxy_ifeval"])

    @pytest.mark.asyncio
    async def test_evaluate_genome_with_llm_call_scores_real_benchmarks(self):
        harness = EvalHarness(benchmark_fidelity="proxy")
        g = _genome("eval")

        async def llm_call(messages, **kwargs):
            return "a plain response"

        results = await harness.evaluate_genome(
            g, benchmarks=["proxy_ifeval", "proxy_gaia"], llm_call=llm_call
        )
        assert len(results) == 2
        for r in results:
            assert 0.0 <= r.score <= 1.0
            assert r.metadata.get("fidelity") == "proxy"
