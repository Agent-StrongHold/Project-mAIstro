"""Behavioral proof for #51: the shipped Evolve cycle uses canonical execution."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from routes.evolution import trigger_cycle
from services.evolution import _EvolutionService
from services.evolution_graph import (
    FinalizeReconciliationRequired,
    _BattleInput,
    _evaluate_one,
    _finalize_cycle,
    _TournamentWork,
    run_canonical_evolution_cycle,
)

import maistro_evolve.cycle as cycle_module
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.graph.nodes import NodeContext, NodeResult
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
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
        self._cycle_markers: dict[str, dict[str, Any]] = {}

    def add(self, genome: _Genome) -> None:
        self._items[genome.id] = genome

    def get(self, genome_id: str) -> _Genome | None:
        return self._items.get(genome_id)

    def list_all(self) -> list[_Genome]:
        return list(self._items.values())

    def cull_bottom(self, pct: float) -> int:
        return 0

    def record_cycle_marker(self, marker_id: str, payload: dict[str, Any]) -> None:
        self._cycle_markers[marker_id] = payload

    def get_cycle_marker(self, marker_id: str) -> dict[str, Any] | None:
        return self._cycle_markers.get(marker_id)


class _Harness:
    fidelity = "proxy"

    async def evaluate_genome(
        self,
        genome: _Genome,
        benchmarks: list[str],
        llm_call: Any,
    ):
        if llm_call is not None:
            await llm_call([{"role": "user", "content": genome.id}])
        return [
            SimpleNamespace(
                benchmark=benchmarks[0],
                score=0.5 if genome.id == "g1" else 0.7,
                cost_usd=0.01,
                duration_seconds=0.1,
                metadata={},
            )
        ]


class _ContextualCall:
    def __init__(self) -> None:
        self.contexts: list[NodeContext] = []

    def for_context(self, ctx: NodeContext) -> Any:
        self.contexts.append(ctx)

        async def call(_messages: Any, **_kwargs: Any) -> str:
            return "model response"

        return call


class _Tournament:
    def __init__(self) -> None:
        self.battles: list[tuple[str, str, str]] = []
        self._published: set[tuple[str, str]] = set()

    def record_battle(
        self,
        *,
        benchmark: str,
        genome_a_id: str,
        genome_b_id: str,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
        **_: Any,
    ) -> None:
        key = (node_run_id or "", benchmark)
        if node_run_id and key in self._published:
            return
        if node_run_id:
            self._published.add(key)
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
    def _fold_score(
        genome: _Genome,
        benchmark: str,
        score: float,
        stub: bool,
        alpha: float,
    ) -> None:
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

    async def _self_improve_top(
        self,
        population: _Population,
        config: Any,
        llm_call: Any,
    ) -> None:
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


def _config(
    *,
    population_size: int,
    eval_batch_size: int,
    benchmarks: list[str] | None = None,
):
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
    contextual_call = _ContextualCall()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(population_size=3, eval_batch_size=2),
        harness=_Harness(),
        llm_call=contextual_call,
        cycle_number=1,
        container=owner,
    )

    assert record.run.status is RunStatus.COMPLETED
    assert [ctx.node_id for ctx in contextual_call.contexts] == [
        "evolve-evaluate-1",
        "evolve-evaluate-2",
        "evolve-finalize",
    ]
    assert all(ctx.run_id == record.run_id for ctx in contextual_call.contexts)
    assert all(ctx.node_run_id and ctx.attempt_id for ctx in contextual_call.contexts)
    assert all(ctx.project_id for ctx in contextual_call.contexts)
    assert len({ctx.project_id for ctx in contextual_call.contexts}) == 1
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


@pytest.mark.parametrize("failure_stage", ["battle", "finalization"])
@pytest.mark.asyncio
async def test_battle_and_finalization_failures_are_canonical_run_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    """Failures after evaluation still terminalize the canonical Run."""

    class _BattleFailureTournament(_Tournament):
        def record_battle(
            self, *, benchmark: str, genome_a_id: str, genome_b_id: str, **_: Any
        ) -> None:
            raise RuntimeError("synthetic battle failure")

    class _FinalizationFailureCycle(_Cycle):
        def _compute_all_fitness(self, population: _Population) -> list[_Genome]:
            raise RuntimeError("synthetic finalization failure")

    monkeypatch.setattr(
        cycle_module,
        "EvolutionCycle",
        _FinalizationFailureCycle if failure_stage == "finalization" else _Cycle,
    )
    population = _Population([_Genome("g1"), _Genome("g2")])
    tournament = _BattleFailureTournament() if failure_stage == "battle" else _Tournament()
    owner = await _container()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(population_size=2, eval_batch_size=2),
        harness=_Harness(),
        container=owner,
    )

    assert record.run.status is RunStatus.FAILED
    assert failure_stage in {"battle", "finalization"}
    assert failure_stage in (record.run.error or "")
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    failed = [item for item in node_runs if item.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].node_id == (
        "evolve-battle-1" if failure_stage == "battle" else "evolve-finalize"
    )
    attempts = await owner.run_store.list_attempts(failed[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED
    physical = NodeResult.model_validate(attempts[0].result)
    assert physical.success is False
    assert physical.error_code == "RuntimeError"


@pytest.mark.parametrize("failure_stage", ["evaluation", "battle", "finalization"])
@pytest.mark.asyncio
async def test_cycle_route_projects_real_canonical_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    """The public route preserves failures returned by the real graph runner."""
    import maistro_evolve.harness as harness_module

    class _RouteHarness(_Harness):
        def __init__(self, benchmark_fidelity: str = "proxy") -> None:
            self.fidelity = benchmark_fidelity

    class _EvaluationFailureHarness(_RouteHarness):
        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
            del genome, benchmarks, llm_call
            raise RuntimeError("synthetic evaluation failure")

    class _BattleFailureTournament(_Tournament):
        def record_battle(
            self, *, benchmark: str, genome_a_id: str, genome_b_id: str, **_: Any
        ) -> None:
            del benchmark, genome_a_id, genome_b_id
            raise RuntimeError("synthetic battle failure")

    class _FinalizationFailureCycle(_Cycle):
        def _compute_all_fitness(self, population: _Population) -> list[_Genome]:
            del population
            raise RuntimeError("synthetic finalization failure")

    import services.engine as engine_module
    import services.evolution as evolution_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )
    monkeypatch.setattr(
        harness_module,
        "EvalHarness",
        _EvaluationFailureHarness if failure_stage == "evaluation" else _RouteHarness,
    )
    monkeypatch.setattr(
        cycle_module,
        "EvolutionCycle",
        _FinalizationFailureCycle if failure_stage == "finalization" else _Cycle,
    )

    population = _Population([_Genome("g1"), _Genome("g2")])
    tournament = _BattleFailureTournament() if failure_stage == "battle" else _Tournament()
    service = _EvolutionService()
    service._population = population
    service._tournament = tournament
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    with pytest.raises(HTTPException) as caught:
        await trigger_cycle(SimpleNamespace(state=SimpleNamespace(user_id="principal")))

    assert caught.value.status_code == 500
    detail = caught.value.detail
    assert detail["code"] == "canonical_run_failed"
    assert detail["status"] == "failed"
    assert detail["run_id"] == service.last_run_id
    assert failure_stage in detail["diagnostic"]
    assert "evolution service not started" not in detail["message"]
    assert service.cycle_count == 0
    status = service.status()
    assert status["running"] is True
    assert status["execution_available"] is True
    assert status["last_run_status"] == "failed"
    assert failure_stage in status["last_error"]

    stored = await owner.run_store.get_run(detail["run_id"])
    assert stored is not None
    assert stored.status is RunStatus.FAILED
    failed_nodes = [
        item
        for item in await owner.run_store.list_node_runs(detail["run_id"])
        if item.status is RunStatus.FAILED
    ]
    assert len(failed_nodes) == 1
    assert (
        failed_nodes[0].node_id
        == {
            "evaluation": "evolve-evaluate-1",
            "battle": "evolve-battle-1",
            "finalization": "evolve-finalize",
        }[failure_stage]
    )


@pytest.mark.asyncio
async def test_successful_cycle_route_projects_completed_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed canonical Run remains the only completed cycle projection."""
    import services.engine as engine_module
    import services.evolution as evolution_module

    import maistro_evolve.harness as harness_module

    class _RouteHarness(_Harness):
        def __init__(self, benchmark_fidelity: str = "proxy") -> None:
            self.fidelity = benchmark_fidelity

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )
    monkeypatch.setattr(harness_module, "EvalHarness", _RouteHarness)
    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)

    service = _EvolutionService()
    service._population = _Population([_Genome("g1"), _Genome("g2")])
    service._tournament = _Tournament()
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    response = await trigger_cycle(SimpleNamespace(state=SimpleNamespace(user_id="principal")))

    assert response["status"] == "completed"
    assert response["cycle_count"] == 1
    assert response["run_id"] == service.last_run_id
    stored = await owner.run_store.get_run(response["run_id"])
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_seeding_during_evaluation_cannot_expand_frozen_pair_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SeedingHarness(_Harness):
        def __init__(self) -> None:
            self._seeded = False

        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
            if not self._seeded:
                population.add(_Genome("seeded"))
                seeded = population.get("seeded")
                assert seeded is not None
                seeded.eval_scores["proxy"] = 0.99
                self._seeded = True
            return await super().evaluate_genome(genome, benchmarks, llm_call)

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    population = _Population([_Genome("g1"), _Genome("g2")])
    owner = await _container()

    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=_Tournament(),
        config=_config(population_size=3, eval_batch_size=2),
        harness=_SeedingHarness(),
        container=owner,
    )

    stored = await owner.run_store.get_run(record.run_id)
    assert stored is not None
    assert stored.provenance["evolve_membership_ids"] == ["g1", "g2"]
    assert stored.provenance["evolve_battle_capacity"] == 1
    plan = next(
        item
        for item in await owner.run_store.list_node_runs(record.run_id)
        if item.node_id == "evolve-plan-pairs"
    )
    assert {frozenset(pair) for pair in plan.result["pairs"]} == {frozenset({"g1", "g2"})}
    assert all("seeded" not in pair for pair in plan.result["pairs"])
    assert record.run.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_post_seed_during_real_cycle_is_admitted_after_pair_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import services.evolution as evolution_service
    from fastapi import FastAPI
    from routes import evolution as evolution_routes

    import maistro_evolve.harness as harness_module
    from maistro.runs.model import RunStatus

    evaluation_started = asyncio.Event()
    release_evaluation = asyncio.Event()

    class _PausingHarness(_Harness):
        def __init__(self, *, benchmark_fidelity: str) -> None:
            self.fidelity = benchmark_fidelity

        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
            evaluation_started.set()
            await release_evaluation.wait()
            return await super().evaluate_genome(genome, benchmarks, llm_call)

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    monkeypatch.setattr(
        cycle_module,
        "EvolutionConfig",
        lambda **_: _config(population_size=3, eval_batch_size=2),
    )
    monkeypatch.setattr(harness_module, "EvalHarness", _PausingHarness)
    owner = await _container()
    import services.engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )
    monkeypatch.setattr(
        "maistro_evolve.diversity.emergency_spawn",
        lambda _existing, count: [_Genome(f"seed-{index}") for index in range(count)],
    )

    population = _Population([_Genome("g1"), _Genome("g2")])
    service = evolution_service._EvolutionService()
    service._population = population
    service._tournament = _Tournament()
    previous = evolution_service._service
    evolution_service._service = service
    try:
        app = FastAPI()
        app.include_router(evolution_routes.router, prefix="/v1/evolution")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            cycle_task = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await evaluation_started.wait()
            seed_task = asyncio.create_task(client.post("/v1/evolution/seed", json={"count": 1}))
            await asyncio.sleep(0)
            assert seed_task.done() is False

            release_evaluation.set()
            cycle_response = await cycle_task
            seed_response = await seed_task
    finally:
        evolution_service._service = previous

    assert cycle_response.status_code == 200
    assert cycle_response.json()["status"] == "completed"
    assert seed_response.status_code == 200
    assert seed_response.json() == {"seeded": 1, "population_size": 4}
    record = await owner.run_store.get_run(cycle_response.json()["run_id"])
    assert record is not None
    assert record.status is RunStatus.COMPLETED
    plan = next(
        item
        for item in await owner.run_store.list_node_runs(record.run_id)
        if item.node_id == "evolve-plan-pairs"
    )
    assert {frozenset(pair) for pair in plan.result["pairs"]} == {frozenset({"g1", "g2"})}
    assert all("seed-0" not in pair for pair in plan.result["pairs"])


@pytest.mark.asyncio
async def test_post_seed_during_battle_traversal_cannot_change_persisted_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import services.evolution as evolution_service
    import services.evolution_graph as evolution_graph
    from fastapi import FastAPI
    from routes import evolution as evolution_routes

    battle_started = asyncio.Event()
    release_battle = asyncio.Event()

    async def _pausing_battle(self: Any, inputs: Any, ctx: Any) -> Any:
        if not battle_started.is_set():
            battle_started.set()
            await release_battle.wait()
        return await original_battle(self, inputs, ctx)

    original_battle = evolution_graph._BattleNode._execute
    monkeypatch.setattr(evolution_graph._BattleNode, "_execute", _pausing_battle)
    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    monkeypatch.setattr(
        cycle_module,
        "EvolutionConfig",
        lambda **_: _config(population_size=5, eval_batch_size=4),
    )

    class _RouteHarness(_Harness):
        def __init__(self, *, benchmark_fidelity: str) -> None:
            self.fidelity = benchmark_fidelity

    import maistro_evolve.harness as harness_module

    monkeypatch.setattr(harness_module, "EvalHarness", _RouteHarness)
    owner = await _container()
    import services.engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )
    monkeypatch.setattr(
        "maistro_evolve.diversity.emergency_spawn",
        lambda _existing, count: [_Genome(f"seed-{index}") for index in range(count)],
    )

    population = _Population([_Genome(f"g{index}") for index in range(1, 5)])
    service = evolution_service._EvolutionService()
    service._population = population
    service._tournament = _Tournament()
    previous = evolution_service._service
    evolution_service._service = service
    try:
        app = FastAPI()
        app.include_router(evolution_routes.router, prefix="/v1/evolution")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            cycle_task = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await battle_started.wait()
            seed_task = asyncio.create_task(client.post("/v1/evolution/seed", json={"count": 1}))
            await asyncio.sleep(0)
            assert seed_task.done() is False

            release_battle.set()
            cycle_response = await cycle_task
            seed_response = await seed_task
    finally:
        evolution_service._service = previous

    assert cycle_response.status_code == 200
    assert seed_response.status_code == 200
    assert seed_response.json() == {"seeded": 1, "population_size": 6}

    run_id = cycle_response.json()["run_id"]
    record = await owner.run_store.get_run(run_id)
    assert record is not None
    assert record.status is RunStatus.COMPLETED
    assert record.provenance["evolve_membership_ids"] == ["g1", "g2", "g3", "g4"]
    assert record.provenance["evolve_battle_capacity"] == 2

    node_runs = await owner.run_store.list_node_runs(run_id)
    plan = next(item for item in node_runs if item.node_id == "evolve-plan-pairs")
    battles = [item for item in node_runs if item.node_id.startswith("evolve-battle-")]
    assert len(plan.result["pairs"]) == len(battles) == 2
    planned = {tuple(pair) for pair in plan.result["pairs"]}
    assert all(
        (item.result["genome_a_id"], item.result["genome_b_id"]) in planned for item in battles
    )
    assert all("seed-0" not in pair for pair in plan.result["pairs"])
    assert len([item for item in node_runs if item.node_id == "evolve-finalize"]) == 1
    for node_run in battles:
        attempts = await owner.run_store.list_attempts(node_run.node_run_id)
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.COMPLETED


@pytest.mark.asyncio
async def test_racing_post_cycle_requests_persist_separate_canonical_plans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import services.evolution as evolution_service
    from fastapi import FastAPI
    from routes import evolution as evolution_routes

    evaluation_started = asyncio.Event()
    release_evaluation = asyncio.Event()

    class _PausingHarness(_Harness):
        def __init__(self, *, benchmark_fidelity: str) -> None:
            self.fidelity = benchmark_fidelity

        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
            if not evaluation_started.is_set():
                evaluation_started.set()
                await release_evaluation.wait()
            return await super().evaluate_genome(genome, benchmarks, llm_call)

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    monkeypatch.setattr(
        cycle_module,
        "EvolutionConfig",
        lambda **_: _config(population_size=5, eval_batch_size=4),
    )
    import maistro_evolve.harness as harness_module

    monkeypatch.setattr(harness_module, "EvalHarness", _PausingHarness)
    owner = await _container()
    import services.engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    population = _Population([_Genome(f"g{index}") for index in range(1, 5)])
    service = evolution_service._EvolutionService()
    service._population = population
    service._tournament = _Tournament()
    previous = evolution_service._service
    evolution_service._service = service
    try:
        app = FastAPI()
        app.include_router(evolution_routes.router, prefix="/v1/evolution")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await evaluation_started.wait()
            second = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await asyncio.sleep(0)
            assert second.done() is False

            release_evaluation.set()
            first_response = await first
            second_response = await second
    finally:
        evolution_service._service = previous

    assert first_response.status_code == second_response.status_code == 200
    assert first_response.json()["run_id"] != second_response.json()["run_id"]
    assert service.cycle_count == 2

    for response in (first_response, second_response):
        run_id = response.json()["run_id"]
        record = await owner.run_store.get_run(run_id)
        assert record is not None
        assert record.status is RunStatus.COMPLETED
        node_runs = await owner.run_store.list_node_runs(run_id)
        plan = next(item for item in node_runs if item.node_id == "evolve-plan-pairs")
        battles = [item for item in node_runs if item.node_id.startswith("evolve-battle-")]
        assert len(plan.result["pairs"]) == len(battles)
        planned = {tuple(pair) for pair in plan.result["pairs"]}
        observed = {(item.result["genome_a_id"], item.result["genome_b_id"]) for item in battles}
        assert observed == planned
        assert record.provenance["evolve_battle_capacity"] >= len(plan.result["pairs"])
        assert (
            record.graph.materialize().metadata["evolve_membership_ids"]
            == record.provenance["evolve_membership_ids"]
        )
        assert len([item for item in node_runs if item.node_id == "evolve-finalize"]) == 1
        for battle in battles:
            attempts = await owner.run_store.list_attempts(battle.node_run_id)
            assert len(attempts) == 1
            assert attempts[0].status is AttemptStatus.COMPLETED


@pytest.mark.asyncio
async def test_missing_has_more_successor_fails_before_recording_unroutable_battle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_graph as evolution_graph

    original_build_graph = evolution_graph._build_graph

    def _malformed_graph(**kwargs: Any):
        graph = original_build_graph(**kwargs)
        graph.edges = [
            edge
            for edge in graph.edges
            if not (edge.from_node == "evolve-battle-1" and edge.to_node == "evolve-battle-2")
        ]
        return graph

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _Cycle)
    monkeypatch.setattr(evolution_graph, "_build_graph", _malformed_graph)
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

    assert record.run.status is RunStatus.FAILED
    assert "has no executable successor" in (record.run.error or "")
    assert tournament.battles == []
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "evolve-evaluate-1",
        "evolve-evaluate-2",
        "evolve-evaluate-3",
        "evolve-evaluate-4",
        "evolve-plan-pairs",
        "evolve-battle-1",
    ]
    assert all(item.status is RunStatus.COMPLETED for item in node_runs[:-1])
    assert node_runs[-1].status is RunStatus.FAILED
    assert not any(item.node_id == "evolve-finalize" for item in node_runs)


@pytest.mark.asyncio
async def test_failed_model_effect_does_not_publish_evaluation_mutation() -> None:
    """A benchmark that swallows a provider error cannot make a score stick."""

    class _FailureCall:
        first_failure: BaseException | None = None

        def for_context(self, _ctx: NodeContext) -> Any:
            bound = self
            bound.governed_model_call = self
            return bound

        async def __call__(self, _messages: Any, **_kwargs: Any) -> str:
            self.first_failure = TimeoutError("provider timed out")
            raise self.first_failure

    class _FailureHarness:
        async def evaluate_genome(
            self, _genome: Any, _benchmarks: list[str], llm_call: Any
        ) -> list[Any]:
            with pytest.raises(TimeoutError):
                await llm_call([{"role": "user", "content": "evaluate"}])
            return [
                SimpleNamespace(
                    benchmark="proxy", score=0.0, cost_usd=0.0, duration_seconds=0.0, metadata={}
                )
            ]

    class _FailureCycle:
        harness = _FailureHarness()

        @staticmethod
        def _fold_score(*_args: Any) -> None:
            raise AssertionError("failed model work must not reach score folding")

    genome = _Genome("failed")
    population = _Population([genome])
    config = _config(population_size=1, eval_batch_size=1)

    with pytest.raises(RuntimeError, match="model effect failed"):
        await _evaluate_one(
            _FailureCycle(),
            population,
            config,
            _FailureCall(),
            "failed",
            NodeContext(
                run_id="run-failed",
                dag_id="graph-failed",
                node_id="evolve-evaluate-1",
                node_run_id="node-failed",
                attempt_id="attempt-failed",
                workspace_id="workspace-evolve",
                project_id="project-evolve",
            ),
        )

    assert genome.eval_scores == {}
    assert genome.harness_params == {}


@pytest.mark.asyncio
async def test_replayed_battle_and_finalize_nodes_do_not_repeat_domain_mutations() -> None:
    """Recovery of one logical NodeRun is at-most-once for domain mutations."""
    population = _Population([_Genome("g1"), _Genome("g2")])
    for genome in population.list_all():
        genome.eval_scores["proxy"] = 0.5
    tournament = _Tournament()
    cycle = _Cycle(harness=_Harness(), tournament=tournament)
    work = _TournamentWork(cycle=cycle, population=population)
    battle_inputs = _BattleInput(pairs=[("g1", "g2")], pair_index=0)
    context = NodeContext(
        run_id="run-recovery",
        dag_id="graph-recovery",
        node_id="evolve-battle-1",
        node_run_id="battle-node-run",
        attempt_id="attempt-1",
    )

    first = work.run_pair(battle_inputs, context)
    second = work.run_pair(battle_inputs, context)
    assert first == second
    assert len(tournament.battles) == 1

    config = _config(population_size=2, eval_batch_size=0)
    finalize_ctx = NodeContext(
        run_id="run-recovery",
        dag_id="graph-recovery",
        node_id="evolve-finalize",
        node_run_id="finalize-node-run",
        attempt_id="attempt-finalize-1",
    )
    finalized = await _finalize_cycle(cycle, population, config, None, finalize_ctx)
    cycle_count = cycle._cycle_count
    replayed_ctx = finalize_ctx.model_copy(update={"attempt_id": "attempt-finalize-2"})
    replayed = await _finalize_cycle(cycle, population, config, None, replayed_ctx)
    assert finalized == replayed
    assert cycle._cycle_count == cycle_count


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
        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
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
        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
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


@pytest.mark.asyncio
async def test_recovered_evaluation_node_run_reuses_published_score_without_reevaluation() -> None:
    class _MustNotRunHarness(_Harness):
        def __init__(self) -> None:
            self.calls = 0

        async def evaluate_genome(
            self,
            genome: _Genome,
            benchmarks: list[str],
            llm_call: Any,
        ):
            self.calls += 1
            raise AssertionError("recovery replayed already-published evaluation work")

    genome = _Genome("g1")
    genome.eval_scores["proxy"] = 0.5
    genome.harness_params["total_cost_usd"] = 0.01
    genome.harness_params["evaluation_runs"] = [
        {
            "run_id": "run-1",
            "node_run_id": "node-run-1",
            "attempt_id": "attempt-before-crash",
        }
    ]
    population = _Population([genome])
    harness = _MustNotRunHarness()
    cycle = _Cycle(harness=harness, tournament=_Tournament())
    ctx = NodeContext(
        run_id="run-1",
        dag_id="graph-1",
        node_id="evolve-evaluate-1",
        node_run_id="node-run-1",
        attempt_id="attempt-after-recovery",
    )

    output = await _evaluate_one(
        cycle,
        population,
        _config(population_size=1, eval_batch_size=1),
        None,
        "g1",
        ctx,
    )

    assert harness.calls == 0
    persisted = population.get("g1")
    assert persisted is not None
    assert persisted.eval_scores == {"proxy": 0.5}
    assert persisted.harness_params["total_cost_usd"] == 0.01
    assert persisted.harness_params["evaluation_runs"] == genome.harness_params["evaluation_runs"]
    assert output.evaluation_attempt_id == "attempt-before-crash"


def test_recovered_battle_node_run_reuses_published_result_without_double_recording() -> None:
    """#1064: a fresh Attempt beneath the same battle NodeRun must not
    re-apply wins/losses/Elo a second time."""
    import maistro_evolve.tournament as tournament_module

    genome_a = SimpleNamespace(id="g1", eval_scores={"proxy": 0.8})
    genome_b = SimpleNamespace(id="g2", eval_scores={"proxy": 0.4})
    population = SimpleNamespace(
        get=lambda gid: {"g1": genome_a, "g2": genome_b}.get(gid),
        list_all=lambda: [genome_a, genome_b],
    )
    tournament = tournament_module.EloTournament()
    cycle = SimpleNamespace(tournament=tournament)
    work = _TournamentWork(cycle=cycle, population=population, membership_ids=["g1", "g2"])

    ctx = NodeContext(
        run_id="run-1",
        dag_id="dag-1",
        node_id="evolve-battle-1",
        node_run_id="battle-node-1",
        attempt_id="attempt-before-crash",
    )
    first = work.run_pair(_BattleInput(pairs=[("g1", "g2")], pair_index=0), ctx)
    elo_after_first = tournament.get_elo("g1", "proxy")
    assert first.battle_node_run_id == "battle-node-1"
    assert tournament.get_stats()["total_battles"] == 1

    recovered_ctx = ctx.model_copy(update={"attempt_id": "attempt-after-recovery"})
    second = work.run_pair(_BattleInput(pairs=[("g1", "g2")], pair_index=0), recovered_ctx)

    assert second == first
    assert tournament.get_stats()["total_battles"] == 1
    assert tournament.get_elo("g1", "proxy") == elo_after_first


@pytest.mark.asyncio
async def test_recovered_finalize_node_run_reuses_published_result_without_double_mutation() -> (
    None
):
    """#1064: a fresh Attempt beneath the same finalize NodeRun must not
    re-cull/re-breed/re-advance the cycle counter a second time."""
    monkeypatch_calls = {"compute_fitness": 0}

    class _CountingCycle(_Cycle):
        def _compute_all_fitness(self, population: _Population) -> list[_Genome]:
            monkeypatch_calls["compute_fitness"] += 1
            return super()._compute_all_fitness(population)

    genome_a, genome_b = _Genome("g1"), _Genome("g2")
    genome_a.eval_scores["proxy"] = 0.5
    genome_b.eval_scores["proxy"] = 0.7
    population = _Population([genome_a, genome_b])
    tournament = _Tournament()
    cycle = _CountingCycle(harness=_Harness(), tournament=tournament)
    config = _config(population_size=3, eval_batch_size=2)

    ctx = NodeContext(
        run_id="run-1",
        dag_id="dag-1",
        node_id="evolve-finalize",
        node_run_id="finalize-node-1",
        attempt_id="attempt-before-crash",
    )
    first = await _finalize_cycle(cycle, population, config, None, ctx)
    assert monkeypatch_calls["compute_fitness"] == 1
    assert cycle._cycle_count == 1
    population_size_after_first = len(population.list_all())
    child_after_first = population.get("child")
    assert child_after_first is not None

    recovered_ctx = ctx.model_copy(update={"attempt_id": "attempt-after-recovery"})
    second = await _finalize_cycle(cycle, population, config, None, recovered_ctx)

    assert second == first
    # Compute-fitness (and by extension cull/breed/self-improve) never ran
    # a second time; the cached committed output was returned instead.
    assert monkeypatch_calls["compute_fitness"] == 1
    assert cycle._cycle_count == 1
    assert len(population.list_all()) == population_size_after_first


@pytest.mark.asyncio
async def test_finalize_fault_after_partial_mutation_blocks_automatic_retry() -> None:
    """#1064: faulting after SOME finalization mutations but before the
    Attempt commits must not let a retry silently re-apply or silently
    succeed. It must fail closed until an operator reconciles."""

    class _FaultingCycle(_Cycle):
        def _compute_all_fitness(self, population: _Population) -> list[_Genome]:
            raise RuntimeError("synthetic mid-finalize fault")

    population = _Population([_Genome("g1"), _Genome("g2")])
    cycle = _FaultingCycle(harness=_Harness(), tournament=_Tournament())
    config = _config(population_size=2, eval_batch_size=2)
    ctx = NodeContext(
        run_id="run-1",
        dag_id="dag-1",
        node_id="evolve-finalize",
        node_run_id="finalize-node-1",
        attempt_id="attempt-before-crash",
    )

    with pytest.raises(RuntimeError, match="synthetic mid-finalize fault"):
        await _finalize_cycle(cycle, population, config, None, ctx)

    marker = population.get_cycle_marker("finalize:finalize-node-1")
    assert marker is not None
    assert marker["status"] == "faulted"

    recovered_ctx = ctx.model_copy(update={"attempt_id": "attempt-after-recovery"})
    with pytest.raises(FinalizeReconciliationRequired):
        await _finalize_cycle(cycle, population, config, None, recovered_ctx)


@pytest.mark.asyncio
async def test_finalize_swallowed_model_failure_records_faulted_not_committed() -> None:
    """#1087: a governed model effect that fails during finalization cannot
    let the cycle commit even when the domain code swallows the provider
    error. The finalize marker must record ``faulted`` -- so replay fails
    closed -- rather than ``committed`` over failed physical work."""

    class _ContextualCall:
        """Bound call double mirroring _GovernedModelCall.for_context(): a
        provider timeout sets first_failure and raises; domain code that
        catches the exception still leaves the failure recorded."""

        first_failure: BaseException | None = None

        @property
        def governed_model_call(self) -> Any:
            return self

        async def __call__(self, _messages: Any, **_kwargs: Any) -> str:
            self.first_failure = TimeoutError("provider timed out")
            raise self.first_failure

    class _SwallowingSelfImproveCycle(_Cycle):
        async def _self_improve_top(
            self, population: _Population, config: Any, llm_call: Any
        ) -> None:
            try:
                await llm_call([{"role": "user", "content": "improve"}])
            except TimeoutError:
                # The benchmark loop treats a provider error as a zero score
                # and keeps going -- exactly the swallow #1087 must survive.
                return

    population = _Population([_Genome("g1"), _Genome("g2")])
    for genome in population.list_all():
        genome.eval_scores["proxy"] = 0.5
    cycle = _SwallowingSelfImproveCycle(harness=_Harness(), tournament=_Tournament())
    config = _config(population_size=2, eval_batch_size=2)
    ctx = NodeContext(
        run_id="run-1",
        dag_id="dag-1",
        node_id="evolve-finalize",
        node_run_id="finalize-node-1",
        attempt_id="attempt-1",
    )

    with pytest.raises(RuntimeError, match="Evolve model effect failed"):
        await _finalize_cycle(cycle, population, config, _ContextualCall(), ctx)

    marker = population.get_cycle_marker("finalize:finalize-node-1")
    assert marker is not None
    assert marker["status"] == "faulted"

    recovered_ctx = ctx.model_copy(update={"attempt_id": "attempt-after-recovery"})
    with pytest.raises(FinalizeReconciliationRequired):
        await _finalize_cycle(cycle, population, config, _ContextualCall(), recovered_ctx)


@pytest.mark.asyncio
async def test_finalize_cycle_without_node_context_skips_marker_bookkeeping() -> None:
    """#1064: ``_finalize_cycle`` is also called directly (no durable graph
    Attempt) by callers that never pass ``ctx`` -- its default. With no
    NodeRun to key an idempotency marker on, ``marker_id`` stays ``None``
    and all three ``marker_id is not None`` checks take their False branch:
    finalize still runs and returns a real output, it just records nothing
    into the population's cycle-marker store."""
    genome_a, genome_b = _Genome("g1"), _Genome("g2")
    genome_a.eval_scores["proxy"] = 0.5
    genome_b.eval_scores["proxy"] = 0.7
    population = _Population([genome_a, genome_b])
    cycle = _Cycle(harness=_Harness(), tournament=_Tournament())
    config = _config(population_size=3, eval_batch_size=2)

    output = await _finalize_cycle(cycle, population, config, None)

    assert output.population_size == len(population.list_all())
    assert population.get_cycle_marker("finalize:anything") is None


@pytest.mark.asyncio
async def test_finalize_cycle_fault_without_node_context_propagates_without_marker() -> None:
    """Same fault as the partial-mutation test above, but with no ``ctx``:
    the exception still propagates to the caller (finalize is not made
    idempotent for callers outside a durable graph Attempt), and -- since
    ``marker_id`` is ``None`` -- the except block's own guard also takes its
    False branch, so no faulted marker is recorded anywhere to reconcile."""

    class _FaultingCycle(_Cycle):
        def _compute_all_fitness(self, population: _Population) -> list[_Genome]:
            raise RuntimeError("synthetic mid-finalize fault")

    population = _Population([_Genome("g1"), _Genome("g2")])
    cycle = _FaultingCycle(harness=_Harness(), tournament=_Tournament())
    config = _config(population_size=2, eval_batch_size=2)

    with pytest.raises(RuntimeError, match="synthetic mid-finalize fault"):
        await _finalize_cycle(cycle, population, config, None)

    assert population.get_cycle_marker("finalize:finalize-node-1") is None
