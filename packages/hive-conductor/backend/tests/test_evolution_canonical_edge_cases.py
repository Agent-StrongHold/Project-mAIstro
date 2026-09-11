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
