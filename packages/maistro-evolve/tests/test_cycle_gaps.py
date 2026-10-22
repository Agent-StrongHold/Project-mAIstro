from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
from maistro_evolve.population import PopulationStore
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(name: str = "test") -> PipelineGenome:
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


@pytest.mark.asyncio
async def test_run_tournament_battles_returns_early_with_fewer_than_two_genomes() -> None:
    population = PopulationStore()
    population.add(_genome("only"))
    cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())

    await cycle._run_tournament_battles(population, EvolutionConfig())

    assert cycle.tournament.get_stats()["total_battles"] == 0


@pytest.mark.asyncio
async def test_run_tournament_battles_returns_early_with_fewer_than_two_scored_genomes() -> None:
    population = PopulationStore()
    g1 = _genome("a")
    g1.eval_scores = {"proxy_ifeval": 0.5}
    g2 = _genome("b")
    population.add(g1)
    population.add(g2)
    cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())

    await cycle._run_tournament_battles(population, EvolutionConfig())

    assert cycle.tournament.get_stats()["total_battles"] == 0


@pytest.mark.asyncio
async def test_run_tournament_battles_clears_inherited_elo_without_battles() -> None:
    """A never-battled genome must not keep inherited Elo evidence (#853).

    Crossover/mutation deepcopy the parent's harness_params, so a child that
    sits out the tournament (odd-sized field, no common benchmarks) would
    otherwise collect the parent's Elo bonus.
    """
    population = PopulationStore()
    g1 = _genome("a")
    g1.eval_scores = {"proxy_ifeval": 0.5}
    g2 = _genome("b")
    g2.eval_scores = {"proxy_ifeval": 0.6}
    # Child of a battled parent: inherited evidence, no battles of its own.
    # Its only benchmark shares nothing with the others, so it can never be
    # paired into a battle regardless of the shuffle.
    g3 = _genome("child")
    g3.eval_scores = {"other_benchmark": 0.55}
    g3.harness_params["avg_elo"] = 1400.0
    g3.harness_params["elo_battles"] = 7
    population.add(g1)
    population.add(g2)
    population.add(g3)
    cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())

    await cycle._run_tournament_battles(population, EvolutionConfig())

    assert g3.harness_params.get("avg_elo") is None
    assert g3.harness_params.get("elo_battles") is None


def test_breed_island_does_nothing_for_empty_island() -> None:
    from maistro_evolve.population import IslandPopulation

    population = PopulationStore()
    cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())
    island_pop = IslandPopulation(island_count=1)

    cycle._breed_island(island_pop, 0, population, EvolutionConfig(), cap=5)

    assert population.list_all() == []


@pytest.mark.asyncio
async def test_self_improve_top_returns_early_when_no_positively_scored_genomes() -> None:
    population = PopulationStore()
    g = _genome("unscored")
    g.fitness_score = None
    population.add(g)
    cycle = EvolutionCycle(harness=EvalHarness(), tournament=EloTournament())

    async def llm_call(*args: object, **kwargs: object) -> str:
        raise AssertionError("llm_call should not be invoked when no scored genomes exist")

    await cycle._self_improve_top(population, EvolutionConfig(self_improve=True), llm_call)

    # genome was never touched since the scored-list was empty.
    assert population.get("g-unscored").harness_params == {}


@pytest.mark.asyncio
async def test_run_cycle_uses_breeding_pool_path_when_tournament_has_few_rated_genomes() -> None:
    population = PopulationStore()
    for i in range(4):
        g = _genome(f"s{i}")
        g.fitness_score = float(i) * 10
        population.add(g)

    # No genome carries eval_scores, so _run_tournament_battles' "scored < 2"
    # guard fires and total_genomes_rated stays at 0 — below the "< 2" gate in
    # run_cycle, forcing the get_breeding_pool fallback branch (lines 205-220).
    harness = EvalHarness()
    tournament = EloTournament()
    config = EvolutionConfig(
        population_size=8,
        eval_batch_size=0,
        target_benchmarks=["proxy_ifeval"],
        self_improve=False,
    )

    cycle = EvolutionCycle(harness=harness, tournament=tournament)
    assert tournament.get_stats()["total_genomes_rated"] < 2

    await cycle.run_cycle(population, llm_call=None, config=config)

    assert len(population.list_all()) > 4


@pytest.mark.asyncio
async def test_run_cycle_breeding_pool_fallback_with_fewer_than_two_candidates() -> None:
    population = PopulationStore()
    population.add(_genome("solo"))

    harness = EvalHarness()
    tournament = EloTournament()
    config = EvolutionConfig(
        population_size=4,
        eval_batch_size=0,
        target_benchmarks=["proxy_ifeval"],
        self_improve=False,
        cull_pct=1.0,
    )

    cycle = EvolutionCycle(harness=harness, tournament=tournament)
    assert tournament.get_stats()["total_genomes_rated"] < 2

    # cull_bottom always removes at least one genome, so the sole genome is
    # culled, leaving the breeding pool empty — pa/pb fall back to None/None
    # and no child is bred (lines 216-217).
    await cycle.run_cycle(population, llm_call=None, config=config)

    assert population.list_all() == []
