"""Focused edge evidence for Evolve's canonical execution adapter (#51)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.nodes.base import NodeContext
from services.evolution import _EvolutionService
from services.evolution_graph import (
    _BattleInput,
    _TournamentWork,
    _append_execution_ref,
    _published_evaluation_ref,
)
from routes.evolution import _actor_principal_id, trigger_cycle


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
