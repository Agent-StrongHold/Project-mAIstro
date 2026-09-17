"""Coverage for the Conductor Evolve service and its canonical cycle dispatch.

Covers:
- start_evolution / stop_evolution singleton lifecycle
- get_evolution_service: raises when not started, returns service when started
- _EvolutionService.stop flips _running flag
- cycle_count / population / tournament properties
- run_loop: maistro_evolve import failure -> log + early return
- run_loop: successful init then graceful stop
- run_loop: _run_one_cycle exception captured into _last_cycle_error
- _run_one_cycle: dispatches to canonical graph runner + increments counter
- _run_one_cycle: failed canonical Run is surfaced and not counted as a cycle
- _build_llm_call: no settings -> None; with settings -> callable
- _build_llm_call inner call: posts to base_url + parses content
- status: returns running, cycle_count, canonical run id, population, error, tournament
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _reset_singleton():
    import services.evolution as evo

    prev = evo._service
    evo._service = None
    yield
    evo._service = prev


# --- singleton lifecycle -------------------------------------------------


def test_get_evolution_service_raises_when_not_started() -> None:
    from services.evolution import get_evolution_service

    with pytest.raises(RuntimeError, match="not started"):
        get_evolution_service()


def test_start_then_get_returns_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """start_evolution sets the singleton; get_evolution_service returns it."""
    import services.evolution as evo

    started: list[Any] = []

    def _capture(coro: Any) -> Any:
        started.append(coro)
        # Don't actually start; close so no warning
        coro.close()
        return None

    monkeypatch.setattr(evo.asyncio, "ensure_future", _capture)
    asyncio.run(evo.start_evolution())
    assert evo._service is not None
    assert started == []
    assert evo._service.status()["availability"] == "degraded"
    assert evo._service.status()["running"] is False
    inst = evo.get_evolution_service()
    assert inst is evo._service


async def test_start_evolution_schedules_cadence_when_owner_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_module
    import services.evolution as evo

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )
    scheduled: list[Any] = []

    def _capture(coro: Any) -> str:
        scheduled.append(coro)
        coro.close()
        return "task-sentinel"

    monkeypatch.setattr(evo.asyncio, "ensure_future", _capture)
    await evo.start_evolution()
    try:
        assert len(scheduled) == 1
        assert evo._service is not None
        assert evo._service.task == "task-sentinel"
        assert evo._service.status()["running"] is True
    finally:
        await evo.stop_evolution()


def test_initialize_domain_state_is_idempotent() -> None:
    from services.evolution import _EvolutionService

    service = _EvolutionService()
    population = object()
    tournament = object()
    service._population = population
    service._tournament = tournament
    service.initialize_domain_state()
    assert service.population is population
    assert service.tournament is tournament


async def test_run_loop_stops_when_owner_degrades_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_module
    import services.evolution as evo
    import services.evolution_graph as evolution_graph
    from services.evolution import _EvolutionService
    from services.evolution_graph import CanonicalExecutionUnavailable

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    checks = 0

    def _owner() -> Any:
        nonlocal checks
        checks += 1
        if checks >= 3:
            raise CanonicalExecutionUnavailable("Container disappeared", availability="degraded")
        return owner

    monkeypatch.setattr(engine_module, "get_engine", lambda: SimpleNamespace())
    monkeypatch.setattr(evolution_graph, "canonical_execution_owner", _owner)
    service = _EvolutionService()
    service._population = SimpleNamespace(list_all=lambda: [])
    service._tournament = object()

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(evo.asyncio, "sleep", _no_sleep)
    await service.run_loop()
    assert checks == 3
    assert service.execution_available is False
    assert service.status()["availability"] == "degraded"


def test_stop_when_not_started_is_noop() -> None:
    import services.evolution as evo

    assert evo._service is None
    asyncio.run(evo.stop_evolution())
    assert evo._service is None


def test_stop_flips_running_and_clears_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evo

    def _swallow(coro: Any) -> Any:
        coro.close()
        return None

    monkeypatch.setattr(evo.asyncio, "ensure_future", _swallow)
    asyncio.run(evo.start_evolution())
    svc = evo._service
    assert svc is not None
    asyncio.run(evo.stop_evolution())
    assert evo._service is None
    assert svc._running is False  # type: ignore[union-attr]


# --- _EvolutionService properties + stop --------------------------------


def test_service_properties_initial_state() -> None:
    from services.evolution import _EvolutionService

    s = _EvolutionService()
    assert s.cycle_count == 0
    assert s.population is None
    assert s.tournament is None
    assert s.last_run_id is None
    assert s._running is True
    assert s.execution_available is False
    s.stop()
    assert s._running is False


# --- run_loop import-failure path ---------------------------------------


def test_run_loop_logs_and_returns_when_maistro_evolve_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When maistro_evolve.population is missing, run_loop returns instead of hanging."""
    from services.evolution import _EvolutionService

    class _Broken:
        def __getattr__(self, name: str) -> Any:
            raise ImportError(f"synthetic: no {name}")

    monkeypatch.setitem(sys.modules, "maistro_evolve.population", _Broken())

    s = _EvolutionService()
    asyncio.run(asyncio.wait_for(s.run_loop(), timeout=2.0))
    assert s.population is None


# --- run_loop successful path -------------------------------------------


def test_run_loop_initializes_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initialize population + tournament, take one short sleep, stop."""
    import types

    import services.evolution as evo
    from services.evolution import _EvolutionService

    class _StubPop:
        def __init__(self) -> None:
            pass

        def list_all(self) -> list[Any]:
            return []

    class _StubTour:
        def get_stats(self) -> dict[str, Any]:
            return {"n": 0}

    pop_mod = types.ModuleType("maistro_evolve.population")
    pop_mod.PopulationStore = _StubPop  # type: ignore[attr-defined]
    tour_mod = types.ModuleType("maistro_evolve.tournament")
    tour_mod.EloTournament = _StubTour  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro_evolve.population", pop_mod)
    monkeypatch.setitem(sys.modules, "maistro_evolve.tournament", tour_mod)

    s = _EvolutionService()

    async def _no_sleep(_: float) -> None:
        s.stop()

    monkeypatch.setattr(evo.asyncio, "sleep", _no_sleep)
    asyncio.run(asyncio.wait_for(s.run_loop(), timeout=2.0))
    assert isinstance(s.population, _StubPop)
    assert isinstance(s.tournament, _StubTour)


def test_run_loop_captures_cycle_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If _run_one_cycle raises, run_loop stores the message and continues."""
    import types

    import services.evolution as evo
    from services.evolution import _EvolutionService

    class _Pop:
        def list_all(self) -> list[Any]:
            return []

    class _Tour:
        pass

    pop_mod = types.ModuleType("maistro_evolve.population")
    pop_mod.PopulationStore = _Pop  # type: ignore[attr-defined]
    tour_mod = types.ModuleType("maistro_evolve.tournament")
    tour_mod.EloTournament = _Tour  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro_evolve.population", pop_mod)
    monkeypatch.setitem(sys.modules, "maistro_evolve.tournament", tour_mod)

    s = _EvolutionService()
    calls = [0]

    async def _flaky_cycle(self_: Any, **_: Any) -> str:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("synthetic cycle error")
        self_.stop()
        return "run-2"

    import services.evolution_graph as evolution_graph

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        evolution_graph, "canonical_execution_owner", lambda *_args, **_kwargs: owner
    )
    monkeypatch.setattr(_EvolutionService, "_run_one_cycle", _flaky_cycle)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(evo.asyncio, "sleep", _no_sleep)

    asyncio.run(asyncio.wait_for(s.run_loop(), timeout=2.0))
    assert "synthetic cycle error" in (s._last_cycle_error or "")
    assert calls[0] >= 2


# --- _run_one_cycle --------------------------------------------------


def test_run_one_cycle_dispatches_canonical_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_graph as evolution_graph
    from services.evolution import _EvolutionService

    from maistro.runs.model import RunStatus

    captured: dict[str, Any] = {}

    class _StubPop:
        def list_all(self) -> list[Any]:
            return [1, 2, 3]

    class _StubTour:
        pass

    async def _canonical(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(
            run_id="canonical-evolve-run",
            run=SimpleNamespace(status=RunStatus.COMPLETED, error=None),
        )

    monkeypatch.setattr(evolution_graph, "run_canonical_evolution_cycle", _canonical)

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        evolution_graph, "canonical_execution_owner", lambda *_args, **_kwargs: owner
    )

    s = _EvolutionService()
    s._population = _StubPop()
    s._tournament = _StubTour()
    run_id = asyncio.run(s._run_one_cycle(actor_principal_id="user-1"))

    assert run_id == "canonical-evolve-run"
    assert s.cycle_count == 1
    assert s.last_run_id == "canonical-evolve-run"
    assert captured["population"] is s._population
    assert captured["tournament"] is s._tournament
    assert captured["actor_principal_id"] == "user-1"
    assert captured["cycle_number"] == 1


def test_run_one_cycle_does_not_count_failed_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_graph as evolution_graph
    from services.evolution import _EvolutionService

    from maistro.runs.model import RunStatus

    class _StubPop:
        def list_all(self) -> list[Any]:
            return [1]

    class _StubTour:
        pass

    async def _canonical(**kwargs: Any) -> Any:
        return SimpleNamespace(
            run_id="failed-evolve-run",
            run=SimpleNamespace(status=RunStatus.FAILED, error="evaluation failed"),
        )

    monkeypatch.setattr(evolution_graph, "run_canonical_evolution_cycle", _canonical)

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        evolution_graph, "canonical_execution_owner", lambda *_args, **_kwargs: owner
    )

    s = _EvolutionService()
    s._population = _StubPop()
    s._tournament = _StubTour()

    with pytest.raises(RuntimeError, match=r"failed-evolve-run.*evaluation failed"):
        asyncio.run(s._run_one_cycle())

    assert s.cycle_count == 0
    assert s.last_run_id == "failed-evolve-run"
    assert s.status()["last_run_status"] == "failed"


# --- _build_llm_call ----------------------------------------------------


def test_build_llm_call_returns_none_without_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.evolution import _EvolutionService

    class _NoBase:
        maistro_llm_base_url = ""
        litellm_api_base = ""
        maistro_llm_api_key = ""
        litellm_api_key = ""
        chat_default_model = "stub"

    import config

    monkeypatch.setattr(config, "get_settings", lambda: _NoBase())
    s = _EvolutionService()
    assert s._build_llm_call() is None


def test_build_llm_call_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import config
    from services.evolution import _EvolutionService

    def _boom() -> Any:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(config, "get_settings", _boom)
    s = _EvolutionService()
    assert s._build_llm_call() is None


async def test_build_llm_call_real_call_posts_and_extracts_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When settings have a base URL, _build_llm_call posts and returns content."""
    import httpx
    from services.evolution import _EvolutionService

    class _Settings:
        litellm_api_base = "http://test.example/api"
        maistro_llm_api_key = "test-key"
        litellm_api_key = ""
        chat_default_model = "test-model"

    import config

    monkeypatch.setattr(config, "get_settings", lambda: _Settings())

    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {"choices": [{"message": {"content": "the answer"}}]}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...

        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    s = _EvolutionService()
    llm = s._build_llm_call()
    assert llm is not None
    out = await llm([{"role": "user", "content": "hi"}])
    assert out == "the answer"
    assert captured["url"] == "http://test.example/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"


# --- status -------------------------------------------------------------


def test_status_reports_zero_state_when_nothing_running() -> None:
    from services.evolution import _EvolutionService

    s = _EvolutionService()
    out = s.status()
    assert out["running"] is False
    assert out["execution_available"] is False
    assert out["availability"] == "degraded"
    assert out["domain_state_only"] is True
    assert out["cycle_count"] == 0
    assert out["population_size"] == 0
    assert out["last_error"] is None
    assert out["last_run_id"] is None
    assert out["last_run_status"] is None
    assert out["tournament"] == {}


def test_status_reports_population_size_tournament_and_run() -> None:
    from services.evolution import _EvolutionService

    class _Pop:
        def list_all(self) -> list[int]:
            return [1, 2, 3, 4]

    class _Tour:
        def get_stats(self) -> dict[str, Any]:
            return {"matches": 10}

    s = _EvolutionService()
    s._population = _Pop()
    s._tournament = _Tour()
    s._cycle_count = 7
    s._last_cycle_error = "prev error"
    s._last_run_id = "run-7"
    out = s.status()
    assert out["cycle_count"] == 7
    assert out["population_size"] == 4
    assert out["last_error"] == "prev error"
    assert out["last_run_id"] == "run-7"
    assert out["tournament"] == {"matches": 10}


# --- availability includes domain readiness (Codex review on #1300) ------


def _available_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.engine as engine_module
    import services.evolution_graph as evolution_graph

    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(engine_module, "get_engine", lambda: SimpleNamespace())
    monkeypatch.setattr(evolution_graph, "canonical_execution_owner", lambda *_a, **_k: owner)


def test_a_healthy_engine_without_domain_state_is_not_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine being up is necessary, not sufficient: without a population
    and tournament every cycle fails before admission, so `/status` must not
    say `running` and the frontend must not offer Run Cycle."""
    from services.evolution import _EvolutionService

    _available_owner(monkeypatch)
    service = _EvolutionService()
    assert service.population is None
    assert service.execution_available is False
    out = service.status()
    assert out["running"] is False
    assert out["execution_available"] is False
    assert out["availability"] == "unavailable"
    assert "population is not initialized" in str(out["availability_reason"])


def test_a_failed_domain_init_keeps_execution_unavailable_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.evolution import EvolutionUnavailableError, _EvolutionService

    class _Broken:
        def __getattr__(self, name: str) -> Any:
            raise ImportError(f"synthetic: no {name}")

    monkeypatch.setitem(sys.modules, "maistro_evolve.population", _Broken())
    _available_owner(monkeypatch)
    service = _EvolutionService()
    service.initialize_domain_state()

    assert service.execution_available is False
    out = service.status()
    assert out["running"] is False
    assert "synthetic:" in str(out["availability_reason"])
    with pytest.raises(EvolutionUnavailableError) as raised:
        asyncio.run(service._run_one_cycle())
    assert raised.value.availability == "unavailable"


def test_a_successful_domain_init_turns_execution_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.evolution import _EvolutionService

    _available_owner(monkeypatch)
    service = _EvolutionService()
    service._population = SimpleNamespace(list_all=lambda: [])
    service._tournament = object()
    service.initialize_domain_state()
    assert service.execution_available is True
    assert service.status()["running"] is True


async def test_start_evolution_does_not_schedule_a_cadence_without_domain_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evo

    class _Broken:
        def __getattr__(self, name: str) -> Any:
            raise ImportError(f"synthetic: no {name}")

    monkeypatch.setitem(sys.modules, "maistro_evolve.population", _Broken())
    _available_owner(monkeypatch)
    monkeypatch.setattr(evo.asyncio, "ensure_future", lambda coro: coro.close() or "task-sentinel")
    await evo.start_evolution()
    try:
        assert evo._service is not None
        assert evo._service.task is None, "no cadence for a service that cannot run a cycle"
        assert evo._service.status()["running"] is False
    finally:
        await evo.stop_evolution()
