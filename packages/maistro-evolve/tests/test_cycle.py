from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
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
        store.add(g1)
        store.add(g2)
        champ = store.get_champion()
        assert champ is not None
        assert champ.id == "g-b"

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
