"""Focused edge evidence for Evolve's canonical execution adapter (#51)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from routes.evolution import _actor_principal_id, trigger_cycle
from services.evolution import (
    CanonicalEvolutionRunError,
    EvolutionUnavailableError,
    _EvolutionService,
)
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


def test_stub_engine_is_domain_state_only_and_bridge_degradation_is_not_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_module

    degraded_engine = SimpleNamespace(agent_port=SimpleNamespace(container=None))
    monkeypatch.setattr(engine_module, "get_engine", lambda: degraded_engine)
    service = _EvolutionService()
    out = service.status()
    assert out["running"] is False
    assert out["execution_available"] is False
    assert out["availability"] == "degraded"
    assert out["domain_state_only"] is True


def test_run_one_cycle_rejects_half_initialized_domain_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_graph as evolution_graph

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        evolution_graph, "canonical_execution_owner", lambda *_args, **_kwargs: owner
    )
    service = _EvolutionService()
    service._population = SimpleNamespace()
    service._tournament = None

    with pytest.raises(RuntimeError, match="population is not initialized"):
        asyncio.run(service._run_one_cycle())


def test_stub_cycle_route_returns_explicit_availability_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_module
    import services.evolution as evolution_service
    from adapters.maistro_core import StubAgentPort

    degraded_engine = SimpleNamespace(agent_port=StubAgentPort())
    monkeypatch.setattr(engine_module, "get_engine", lambda: degraded_engine)
    service = _EvolutionService()
    monkeypatch.setattr(evolution_service, "get_evolution_service", lambda: service)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(trigger_cycle(SimpleNamespace(state=SimpleNamespace())))

    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "evolution_unavailable"
    assert caught.value.detail["availability"] == "degraded"
    assert "no Container" in caught.value.detail["message"]


def test_unavailable_cycle_is_distinguishable_from_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Unavailable:
        async def _run_one_cycle(self, **_: Any) -> str:
            raise EvolutionUnavailableError(
                "canonical engine Container is unavailable", availability="degraded"
            )

    import services.evolution as evolution_service

    monkeypatch.setattr(evolution_service, "get_evolution_service", lambda: _Unavailable())
    with pytest.raises(HTTPException) as caught:
        asyncio.run(trigger_cycle(SimpleNamespace(state=SimpleNamespace())))
    assert caught.value.status_code == 503
    assert caught.value.detail == {
        "code": "evolution_unavailable",
        "availability": "degraded",
        "message": "canonical engine Container is unavailable",
    }


@pytest.mark.parametrize(
    ("status", "diagnostic"),
    [
        ("failed", "evaluation failed"),
        ("cancelled", "battle cancelled"),
        ("timed_out", "finalization timed out"),
    ],
)
def test_canonical_run_failure_projects_identity_status_and_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    diagnostic: str,
) -> None:
    class _Failed:
        cycle_count = 0

        async def _run_one_cycle(self, **_: Any) -> str:
            from maistro.runs.model import RunStatus

            raise CanonicalEvolutionRunError(
                run_id="canonical-failed-run",
                status=RunStatus(status),
                diagnostic=diagnostic,
            )

    import services.evolution as evolution_service

    monkeypatch.setattr(evolution_service, "get_evolution_service", lambda: _Failed())
    with pytest.raises(HTTPException) as caught:
        asyncio.run(trigger_cycle(SimpleNamespace(state=SimpleNamespace())))
    assert caught.value.status_code == 500
    assert caught.value.detail == {
        "code": "canonical_run_failed",
        "run_id": "canonical-failed-run",
        "status": status,
        "diagnostic": diagnostic,
        "message": f"Evolution cycle canonical Run canonical-failed-run did not complete: {diagnostic}",
    }


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
