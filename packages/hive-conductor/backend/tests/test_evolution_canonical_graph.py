"""Behavioral proof for #51: the shipped Evolve cycle uses canonical execution."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import maistro_evolve.cycle as cycle_module
from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
from maistro.graph.nodes import NodeResult
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore
from services.evolution_graph import run_canonical_evolution_cycle

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


def _config(*, population_size: int, eval_batch_size: int, benchmarks: list[str] | None = None):
    return SimpleNamespace(
        eval_batch_size=eval_batch_size,
        target_benchmarks=benchmarks or ["proxy"],
        eval_ema_alpha=0.5,
        cull_pct=0.0,
        island_count=1,
        population_size=population_size,
        migration_interval=100,
    )


@pytest.mark.asyncio
async def test_cycle_is_one_run_with_evaluation_battle_finalization_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    population = _Population([_Genome("g1"), _Genome("g2")])
    tournament = _Tournament()
    owner = await _container()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(population_size=3, eval_batch_size=2),
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
async def test_multiple_battle_nodes_finish_before_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    population = _Population([_Genome(f"g{index}") for index in range(1, 5)])
    tournament = _Tournament()
    owner = await _container()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(population_size=5, eval_batch_size=4),
        harness=_Harness(),
        container=owner,
    )

    assert record.run.status is RunStatus.COMPLETED
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "evolve-evaluate-1",
        "evolve-evaluate-2",
        "evolve-evaluate-3",
        "evolve-evaluate-4",
        "evolve-plan-pairs",
        "evolve-battle-1",
        "evolve-battle-2",
        "evolve-finalize",
    ]
    assert len(tournament.battles) == 2


@pytest.mark.asyncio
async def test_unscored_genomes_do_not_create_fake_battle_node_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoResultHarness(_Harness):
        async def evaluate_genome(self, genome: _Genome, benchmarks: list[str], llm_call: Any):
            return []

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    population = _Population([_Genome("g1"), _Genome("g2")])
    owner = await _container()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=_Tournament(),
        config=_config(population_size=2, eval_batch_size=2),
        harness=_NoResultHarness(),
        container=owner,
    )
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    battle_runs = [item for item in node_runs if item.node_id.startswith("evolve-battle-")]
    assert battle_runs == []
    plan_runs = [item for item in node_runs if item.node_id == "evolve-plan-pairs"]
    assert len(plan_runs) == 1
    assert plan_runs[0].result["pair_count"] == 0


@pytest.mark.asyncio
async def test_failed_evaluation_attempt_does_not_publish_partial_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TwoResultHarness(_Harness):
        async def evaluate_genome(self, genome: _Genome, benchmarks: list[str], llm_call: Any):
            return [
                SimpleNamespace(
                    benchmark="first",
                    score=0.4,
                    cost_usd=0.01,
                    duration_seconds=0.1,
                    metadata={},
                ),
                SimpleNamespace(
                    benchmark="second",
                    score=0.6,
                    cost_usd=0.01,
                    duration_seconds=0.1,
                    metadata={},
                ),
            ]

    class _FailingCycle(_Cycle):
        @staticmethod
        def _fold_score(
            genome: _Genome,
            benchmark: str,
            score: float,
            stub: bool,
            alpha: float,
        ) -> None:
            if benchmark == "second":
                raise RuntimeError("synthetic fold failure")
            genome.eval_scores[benchmark] = score

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _FailingCycle)
    population = _Population([_Genome("g1")])
    owner = await _container()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=_Tournament(),
        config=_config(
            population_size=1,
            eval_batch_size=1,
            benchmarks=["first", "second"],
        ),
        harness=_TwoResultHarness(),
        container=owner,
    )

    assert record.run.status is RunStatus.FAILED
    genome = population.get("g1")
    assert genome is not None
    assert genome.eval_scores == {}
    assert "evaluation_runs" not in genome.harness_params

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED
    attempts = await owner.run_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    physical = NodeResult.model_validate(attempts[0].result)
    assert physical.success is False
    assert physical.error_code == "RuntimeError"
