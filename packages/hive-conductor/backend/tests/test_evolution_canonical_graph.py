"""Behavioral proof for #51: the shipped Evolve cycle uses canonical execution."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


class _Genome:
    def __init__(
        self,
        genome_id: str,
        *,
        parent_a_id: str | None = None,
        parent_b_id: str | None = None,
    ) -> None:
        self.id = genome_id
        self.parent_a_id = parent_a_id
        self.parent_b_id = parent_b_id
        self.fitness_score: float | None = None
        self.eval_scores: dict[str, float] = {}
        self.harness_params: dict[str, Any] = {}
        self.updated_at = ""


class _Population:
    def __init__(self, genomes: list[_Genome]) -> None:
        self._items = {genome.id: genome for genome in genomes}

    def add(self, genome: _Genome) -> None:
        self._items[genome.id] = genome

    def get(self, genome_id: str) -> _Genome | None:
        return self._items.get(genome_id)

    def list_all(self) -> list[_Genome]:
        return list(self._items.values())

    def cull_bottom(self, pct: float) -> int:
        return 0


class _Harness:
    fidelity = "proxy"

    async def evaluate_genome(self, genome: _Genome, benchmarks: list[str], llm_call: Any):
        return [
            SimpleNamespace(
                benchmark=benchmarks[0],
                score=0.5 if genome.id == "g1" else 0.7,
                cost_usd=0.01,
                duration_seconds=0.1,
                metadata={},
            )
        ]


class _Tournament:
    def __init__(self) -> None:
        self.battles: list[tuple[str, str, str]] = []

    def record_battle(self, *, benchmark: str, genome_a_id: str, genome_b_id: str, **_: Any) -> None:
        self.battles.append((benchmark, genome_a_id, genome_b_id))

    def get_avg_elo(self, genome_id: str) -> float:
        return 1000.0


class _Cycle:
    """Small domain double; the test is about the execution mapping, not Evolve math."""

    def __init__(self, harness: Any = None, tournament: Any = None) -> None:
        self.harness = harness
        self.tournament = tournament
        self._island_pop: Any = None
        self._cycle_count = 0
        self._child_added = False

    @staticmethod
    def _fold_score(genome: _Genome, benchmark: str, score: float, stub: bool, alpha: float) -> None:
        genome.eval_scores[benchmark] = score

    def _compute_all_fitness(self, population: _Population) -> list[_Genome]:
        for genome in population.list_all():
            genome.fitness_score = sum(genome.eval_scores.values())
        return population.list_all()

    def _breed_island(
        self,
        island_pop: Any,
        island_id: int,
        population: _Population,
        config: Any,
        cap: int,
    ) -> None:
        if not self._child_added:
            population.add(_Genome("child", parent_a_id="g1", parent_b_id="g2"))
            self._child_added = True

    async def _self_improve_top(self, population: _Population, config: Any, llm_call: Any) -> None:
        return None


async def _container() -> Any:
    project_store = InMemoryProjectScopeStore()
    await project_store.create_root("workspace-evolve")
    run_store = InMemoryRunStore(project_store=project_store)
    continuation = InMemoryGraphContinuationStore()
    return SimpleNamespace(
        config=SimpleNamespace(workspace_id="workspace-evolve"),
        project_scope_store=project_store,
        run_store=run_store,
        graph_run_store=CanonicalDurableRunStore(run_store, continuation),
    )


@pytest.mark.asyncio
async def test_cycle_is_one_run_with_evaluation_battle_finalization_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import maistro_evolve.cycle as cycle_module
    from services.evolution_graph import run_canonical_evolution_cycle

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    population = _Population([_Genome("g1"), _Genome("g2")])
    tournament = _Tournament()
    owner = await _container()
    config = SimpleNamespace(
        eval_batch_size=2,
        target_benchmarks=["proxy"],
        eval_ema_alpha=0.5,
        cull_pct=0.0,
        island_count=1,
        population_size=3,
        migration_interval=100,
    )

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=config,
        harness=_Harness(),
        cycle_number=1,
        container=owner,
    )

    assert record.run.status is RunStatus.COMPLETED
    stored = await owner.run_store.get_run(record.run_id)
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED
    assert stored.provenance["admission_source"] == "evolve"

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "evolve-evaluate-1",
        "evolve-evaluate-2",
        "evolve-plan-pairs",
        "evolve-battle-1",
        "evolve-finalize",
    ]
    assert all(item.status is RunStatus.COMPLETED for item in node_runs)

    attempts = []
    for node_run in node_runs:
        attempts.extend(await owner.run_store.list_attempts(node_run.node_run_id))
    assert len(attempts) == len(node_runs)
    assert len({attempt.attempt_id for attempt in attempts}) == len(attempts)

    assert len(tournament.battles) == 1
    for genome_id in ("g1", "g2"):
        genome = population.get(genome_id)
        assert genome is not None
        refs = genome.harness_params["evaluation_runs"]
        assert len(refs) == 1
        assert refs[0]["run_id"] == record.run_id
        assert refs[0]["attempt_id"] in {attempt.attempt_id for attempt in attempts}

    child = population.get("child")
    assert child is not None
    assert {ref["run_id"] for ref in child.harness_params["source_evaluation_runs"]} == {
        record.run_id
    }


@pytest.mark.asyncio
async def test_unscored_genomes_do_not_create_fake_battle_node_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import maistro_evolve.cycle as cycle_module
    from services.evolution_graph import run_canonical_evolution_cycle

    class _NoResultHarness(_Harness):
        async def evaluate_genome(self, genome: _Genome, benchmarks: list[str], llm_call: Any):
            return []

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    population = _Population([_Genome("g1"), _Genome("g2")])
    owner = await _container()
    config = SimpleNamespace(
        eval_batch_size=2,
        target_benchmarks=["proxy"],
        eval_ema_alpha=0.5,
        cull_pct=0.0,
        island_count=1,
        population_size=2,
        migration_interval=100,
    )

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=_Tournament(),
        config=config,
        harness=_NoResultHarness(),
        container=owner,
    )
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    battle_runs = [item for item in node_runs if item.node_id.startswith("evolve-battle-")]
    assert battle_runs == []
    plan_runs = [item for item in node_runs if item.node_id == "evolve-plan-pairs"]
    assert len(plan_runs) == 1
    assert plan_runs[0].result["pair_count"] == 0
