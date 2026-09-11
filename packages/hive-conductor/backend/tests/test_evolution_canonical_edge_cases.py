"""Focused edge evidence for Evolve's canonical execution adapter (#51)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from routes.evolution import SeedPopulationBody, _actor_principal_id, seed_population, trigger_cycle
from services.evolution import _EvolutionService
from services.evolution_graph import (
    _append_execution_ref,
    _BattleInput,
    _published_evaluation_ref,
    _TournamentWork,
)

from maistro.graph.nodes.base import NodeContext


def _evolution_test_app():
    from fastapi import FastAPI
    from routes import evolution as evolution_routes

    app = FastAPI()
    app.include_router(evolution_routes.router, prefix="/v1/evolution")
    return app


def test_actor_provenance_and_cycle_run_id_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = [
        (SimpleNamespace(state=SimpleNamespace(user_id="principal-1", user={})), "principal-1"),
        (SimpleNamespace(state=SimpleNamespace(user_id=None, user={"id": "user-1"})), "user-1"),
        (
            SimpleNamespace(state=SimpleNamespace(user_id=None, user={"username": "alice"})),
            "alice",
        ),
        (SimpleNamespace(state=SimpleNamespace(user_id=None, user="not-a-dict")), None),
        (SimpleNamespace(state=SimpleNamespace(user_id=None, user={})), None),
    ]
    for request, expected in requests:
        assert _actor_principal_id(request) == expected

    captured: dict[str, Any] = {}

    class _Service:
        cycle_count = 7

        async def _run_one_cycle(self, *, actor_principal_id: str | None = None) -> str:
            captured["actor_principal_id"] = actor_principal_id
            return "canonical-run-7"

    import services.evolution as evolution_service

    monkeypatch.setattr(evolution_service, "get_evolution_service", lambda: _Service())
    response = asyncio.run(trigger_cycle(requests[1][0]))
    assert response == {
        "status": "completed",
        "cycle_count": 7,
        "run_id": "canonical-run-7",
    }
    assert captured["actor_principal_id"] == "user-1"


def test_seed_route_uses_the_serialized_service_admission() -> None:
    captured: dict[str, int] = {}

    class _Service:
        async def seed_population(self, count: int) -> tuple[int, int]:
            captured["count"] = count
            return 2, 5

    import services.evolution as evolution_service

    previous = evolution_service._service
    evolution_service._service = _Service()
    try:
        response = asyncio.run(seed_population(SeedPopulationBody(count=4)))
    finally:
        evolution_service._service = previous

    assert response == {"seeded": 2, "population_size": 5}
    assert captured == {"count": 4}


def test_run_one_cycle_rejects_half_initialized_domain_state() -> None:
    service = _EvolutionService()
    service._population = SimpleNamespace()
    service._tournament = None

    with pytest.raises(RuntimeError, match="population is not initialized"):
        asyncio.run(service._run_one_cycle())


def test_execution_refs_ignore_malformed_history_and_do_not_duplicate_attempts() -> None:
    genome = SimpleNamespace(
        harness_params={
            "evaluation_runs": [
                "not-a-record",
                {"node_run_id": "other", "run_id": "run-old", "attempt_id": "attempt-old"},
                {"node_run_id": "node-1", "run_id": "", "attempt_id": "attempt-incomplete"},
            ]
        }
    )
    assert _published_evaluation_ref(genome, "node-1") is None

    ctx = NodeContext(
        run_id="run-1",
        dag_id="dag-1",
        node_id="evaluate-1",
        node_run_id="node-1",
        attempt_id="attempt-1",
    )
    _append_execution_ref(genome, ctx)
    _append_execution_ref(genome, ctx)

    assert _published_evaluation_ref(genome, "node-1") == {
        "run_id": "run-1",
        "node_run_id": "node-1",
        "attempt_id": "attempt-1",
    }
    matching = [
        item
        for item in genome.harness_params["evaluation_runs"]
        if isinstance(item, dict) and item.get("attempt_id") == "attempt-1"
    ]
    assert len(matching) == 1


def test_tournament_work_rejects_pair_plan_beyond_graph_capacity() -> None:
    population = SimpleNamespace(
        get=lambda genome_id: SimpleNamespace(id=genome_id, eval_scores={"proxy": 1.0}),
        list_all=lambda: [],
    )
    work = _TournamentWork(
        cycle=SimpleNamespace(tournament=SimpleNamespace()),
        population=population,
        membership_ids=["g1", "g2", "g3", "g4"],
        battle_slots=1,
    )

    with pytest.raises(RuntimeError, match="no successor"):
        work.run_pair(_BattleInput(pairs=[("g1", "g2"), ("g3", "g4")]))


def test_tournament_work_rejects_corrupt_persisted_pair_work() -> None:
    genome = SimpleNamespace(id="g1", eval_scores={"proxy": 1.0})

    class _Population:
        def get(self, genome_id: str) -> Any:
            return genome if genome_id == "g1" else None

        def list_all(self) -> list[Any]:
            return [genome]

    work = _TournamentWork(
        cycle=SimpleNamespace(tournament=SimpleNamespace()),
        population=_Population(),
    )
    with pytest.raises(RuntimeError, match="outside its persisted pair plan"):
        work.run_pair(_BattleInput(pairs=[("g1", "missing")], pair_index=-1))

    with pytest.raises(ValueError, match="genome disappeared"):
        work.run_pair(_BattleInput(pairs=[("g1", "missing")], pair_index=0))


@pytest.mark.asyncio
async def test_post_seed_waits_before_pair_planning_and_during_battle_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import services.evolution as evolution_service
    import services.evolution_graph as evolution_graph

    from maistro.runs.model import RunStatus

    class _Population:
        def __init__(self) -> None:
            self.items: list[Any] = []

        def list_all(self) -> list[Any]:
            return list(self.items)

        def add(self, genome: Any) -> None:
            self.items.append(genome)

    population = _Population()
    service = _EvolutionService()
    service._population = population
    service._tournament = SimpleNamespace()
    admitted = asyncio.Event()
    begin_pair_planning = asyncio.Event()
    pair_planning = asyncio.Event()
    release_pair_planning = asyncio.Event()
    battle_traversal = asyncio.Event()
    release_battle = asyncio.Event()

    async def _canonical(**_: Any) -> Any:
        admitted.set()
        await begin_pair_planning.wait()
        pair_planning.set()
        await release_pair_planning.wait()
        battle_traversal.set()
        await release_battle.wait()
        return SimpleNamespace(
            run_id="canonical-route-run",
            run=SimpleNamespace(status=RunStatus.COMPLETED, error=None),
        )

    monkeypatch.setattr(evolution_graph, "run_canonical_evolution_cycle", _canonical)
    monkeypatch.setattr(
        "maistro_evolve.diversity.emergency_spawn",
        lambda _existing, count: [SimpleNamespace(id=f"seed-{index}") for index in range(count)],
    )
    previous = evolution_service._service
    evolution_service._service = service
    try:
        app = _evolution_test_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            cycle_task = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await admitted.wait()

            seed_task = asyncio.create_task(client.post("/v1/evolution/seed", json={"count": 1}))
            await asyncio.sleep(0)
            assert seed_task.done() is False

            begin_pair_planning.set()
            await pair_planning.wait()
            assert seed_task.done() is False

            release_pair_planning.set()
            await battle_traversal.wait()
            assert seed_task.done() is False

            release_battle.set()
            cycle_response = await cycle_task
            seed_response = await seed_task
    finally:
        evolution_service._service = previous

    assert cycle_response.status_code == 200
    assert cycle_response.json() == {
        "status": "completed",
        "cycle_count": 1,
        "run_id": "canonical-route-run",
    }
    assert seed_response.status_code == 200
    assert seed_response.json() == {"seeded": 1, "population_size": 1}


@pytest.mark.asyncio
async def test_racing_post_cycle_requests_share_one_cycle_admission_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import services.evolution as evolution_service
    import services.evolution_graph as evolution_graph

    from maistro.runs.model import RunStatus

    class _Population:
        def list_all(self) -> list[Any]:
            return []

    service = _EvolutionService()
    service._population = _Population()
    service._tournament = SimpleNamespace()
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    active = 0
    peak_active = 0
    calls = 0

    async def _canonical(**_: Any) -> Any:
        nonlocal active, peak_active, calls
        calls += 1
        ordinal = calls
        active += 1
        peak_active = max(peak_active, active)
        (first_entered if ordinal == 1 else second_entered).set()
        await (first_release if ordinal == 1 else second_release).wait()
        active -= 1
        return SimpleNamespace(
            run_id=f"canonical-route-run-{ordinal}",
            run=SimpleNamespace(status=RunStatus.COMPLETED, error=None),
        )

    monkeypatch.setattr(evolution_graph, "run_canonical_evolution_cycle", _canonical)
    previous = evolution_service._service
    evolution_service._service = service
    try:
        app = _evolution_test_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await first_entered.wait()
            second = asyncio.create_task(client.post("/v1/evolution/cycle"))
            await asyncio.sleep(0)
            assert second.done() is False
            assert calls == 1
            assert peak_active == 1

            first_release.set()
            first_response = await first
            await second_entered.wait()
            second_release.set()
            second_response = await second
    finally:
        evolution_service._service = previous

    assert first_response.status_code == 200
    assert first_response.json()["run_id"] == "canonical-route-run-1"
    assert second_response.status_code == 200
    assert second_response.json()["run_id"] == "canonical-route-run-2"
    assert service.cycle_count == 2
    assert active == 0
    assert peak_active == 1
