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
<<<<<<< HEAD
        run_store=object(), graph_run_store=object(), project_scope_store=object()
=======
        run_store=object(),
        graph_run_store=object(),
        project_scope_store=object(),
        # `start_evolution` now also starts the recovery cadence (#1064),
        # which reaches `owner.event_bus` on its first tick.
        event_bus=object(),
>>>>>>> 0221d2cd799ec075e30c33e0b2e2fda573865aef
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


<<<<<<< HEAD
=======
# --- #1064 finding 6: recovery cadence brackets the service's own lifecycle,
# not the engine's --------------------------------------------------------


async def test_start_evolution_starts_the_recovery_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cadence must start once ``_service`` exists, closing the window
    where `EngineService.start()` started it before `start_evolution()` ever
    ran -- a due RUNNING Run inspected in that window previously terminalized
    FAILED only because of startup ordering."""
    import services.evolution as evo
    import services.evolution_recovery as recovery_driver

    await recovery_driver.stop_evolution_recovery()
    assert recovery_driver._task is None

    def _swallow(coro: Any) -> Any:
        coro.close()
        return None

    monkeypatch.setattr(evo.asyncio, "ensure_future", _swallow)
    await evo.start_evolution()
    try:
        assert recovery_driver._task is not None
        assert not recovery_driver._task.done()
    finally:
        await evo.stop_evolution()
    assert recovery_driver._task is None


async def test_stop_evolution_stops_the_recovery_cadence_before_clearing_the_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mirror image of start: shutdown previously cleared the singleton
    in `_shutdown_background_services` before `EngineService.stop()` got
    around to cancelling the cadence task, leaving the same
    ``EvolutionServiceNotStarted`` window open at the other end of the
    process's life. ``stop_evolution`` must stop and join the cadence before
    (not after) `_service` becomes `None`."""
    import services.evolution as evo
    import services.evolution_recovery as recovery_driver

    order: list[str] = []
    real_stop = recovery_driver.stop_evolution_recovery

    async def _tracking_stop() -> None:
        order.append("recovery_stopped")
        await real_stop()

    def _swallow(coro: Any) -> Any:
        coro.close()
        return None

    monkeypatch.setattr(evo.asyncio, "ensure_future", _swallow)
    monkeypatch.setattr(recovery_driver, "stop_evolution_recovery", _tracking_stop)
    await evo.start_evolution()
    assert evo._service is not None

    await evo.stop_evolution()
    # The cadence was stopped while `_service` was still set -- proven by
    # recording the observation before `stop_evolution` clears it, not merely
    # that both eventually happened.
    assert order == ["recovery_stopped"]
    assert evo._service is None


async def test_starting_the_engine_alone_does_not_start_the_evolve_recovery_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`EngineService.start()` must no longer start the Evolve recovery
    cadence itself (#1064) -- only `services.evolution.start_evolution` does,
    once the singleton it depends on actually exists. Application startup
    calls `start_engine()` well before `start_evolution()`, so a cadence
    started by the engine would tick against a service that does not exist
    yet."""
    import services.evolution_recovery as recovery_driver
    from services.engine import EngineService

    await recovery_driver.stop_evolution_recovery()
    assert recovery_driver._task is None

    class _Settings:
        maistro_router_api_key = ""
        maistro_base_url = "http://localhost:8000"
        hive_mode = "production"
        hive_default_workspace_id = "default"

    svc = EngineService()
    try:
        await svc.start(_Settings())  # type: ignore[arg-type]
        assert recovery_driver._task is None
    finally:
        await svc.stop()
        await recovery_driver.stop_evolution_recovery()


>>>>>>> 0221d2cd799ec075e30c33e0b2e2fda573865aef
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


# --- record_recovered_run bookkeeping (#1064 finding 4) -----------------


def test_record_recovered_run_completed_increments_cycle_count() -> None:
    from services.evolution import _EvolutionService

    from maistro.runs.model import RunStatus

    s = _EvolutionService()
    assert s.cycle_count == 0

    s.record_recovered_run("recovered-run-1", RunStatus.COMPLETED)

    assert s.cycle_count == 1
    assert s.last_run_id == "recovered-run-1"
    assert s.status()["last_run_status"] == RunStatus.COMPLETED.value
    assert s.status()["last_error"] is None


def test_record_recovered_run_failed_does_not_increment_cycle_count() -> None:
    """The non-COMPLETED branch: a recovered Run that terminalized FAILED
    (or CANCELLED/TIMED_OUT) must not be counted as a completed cycle, and
    must surface an error — mirroring _run_one_cycle_locked's own semantics
    for a live cycle that fails."""
    from services.evolution import _EvolutionService

    from maistro.runs.model import RunStatus

    s = _EvolutionService()

    s.record_recovered_run("recovered-run-2", RunStatus.FAILED, error="boom")

    assert s.cycle_count == 0
    assert s.last_run_id == "recovered-run-2"
    assert s.status()["last_run_status"] == RunStatus.FAILED.value
    assert s.status()["last_error"] == "boom"


def test_record_recovered_run_failed_without_explicit_error_uses_default_message() -> None:
    from services.evolution import _EvolutionService

    from maistro.runs.model import RunStatus

    s = _EvolutionService()

    s.record_recovered_run("recovered-run-3", RunStatus.CANCELLED)

    assert s.cycle_count == 0
    assert s.status()["last_error"] == "canonical Run ended cancelled"


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


@pytest.mark.asyncio
async def test_racing_manual_and_background_cycles_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_graph as evolution_graph
    from services.evolution import _EvolutionService

    from maistro.runs.model import RunStatus

    class _StubPop:
        def list_all(self) -> list[Any]:
            return []

    class _StubTour:
        pass

    entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    peak_active = 0
    calls = 0

    async def _canonical(**_: Any) -> Any:
        nonlocal active, peak_active, calls
        calls += 1
        active += 1
        peak_active = max(peak_active, active)
        entered.set()
        await release.wait()
        active -= 1
        return SimpleNamespace(
            run_id=f"canonical-evolve-run-{calls}",
            run=SimpleNamespace(status=RunStatus.COMPLETED, error=None),
        )

    monkeypatch.setattr(evolution_graph, "run_canonical_evolution_cycle", _canonical)
    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        evolution_graph, "canonical_execution_owner", lambda *_args, **_kwargs: owner
    )
    service = _EvolutionService()
    service._population = _StubPop()
    service._tournament = _StubTour()

    first = asyncio.create_task(service._run_one_cycle())
    await entered.wait()
    second = asyncio.create_task(service._run_one_cycle())
    await asyncio.sleep(0)
    assert calls == 1
    assert peak_active == 1

    release.set()
    assert await first == "canonical-evolve-run-1"
    assert await second == "canonical-evolve-run-2"
    assert service.cycle_count == 2


@pytest.mark.asyncio
async def test_seed_waits_for_active_cycle_and_joins_the_next_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution_graph as evolution_graph
    from services.evolution import _EvolutionService

    import maistro_evolve.diversity as diversity
    from maistro.runs.model import RunStatus

    class _StubPop:
        def list_all(self) -> list[Any]:
            return []

        def add(self, genome: Any) -> None:
            return None

    class _StubTour:
        pass

    entered = asyncio.Event()
    release = asyncio.Event()

    async def _canonical(**_: Any) -> Any:
        entered.set()
        await release.wait()
        return SimpleNamespace(
            run_id="canonical-evolve-run",
            run=SimpleNamespace(status=RunStatus.COMPLETED, error=None),
        )

    monkeypatch.setattr(evolution_graph, "run_canonical_evolution_cycle", _canonical)
    monkeypatch.setattr(diversity, "emergency_spawn", lambda existing, count: [])
    owner = SimpleNamespace(
        run_store=object(), graph_run_store=object(), project_scope_store=object()
    )
    monkeypatch.setattr(
        evolution_graph, "canonical_execution_owner", lambda *_args, **_kwargs: owner
    )
    service = _EvolutionService()
    service._population = _StubPop()
    service._tournament = _StubTour()

    cycle = asyncio.create_task(service._run_one_cycle())
    await entered.wait()
    seed = asyncio.create_task(service.seed_population(3))
    await asyncio.sleep(0)
    assert seed.done() is False

    release.set()
    assert await cycle == "canonical-evolve-run"
    assert await seed == (0, 0)


@pytest.mark.asyncio
async def test_seed_population_without_domain_state_is_rejected() -> None:
    from services.evolution import _EvolutionService

    service = _EvolutionService()
    assert service._population is None

    with pytest.raises(RuntimeError, match="population is not initialized"):
        await service.seed_population(2)


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


def test_build_llm_call_public_accessor_delegates_to_private_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1064: ``build_llm_call`` is the public accessor a restart-recovery
    resolver uses to reconstruct the same llm_call a live cycle would have
    built (it has no other way to reach the private builder). Prove it
    actually delegates, both when the builder succeeds and when it
    declines (no base URL configured)."""
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
    assert s.build_llm_call() is None

    sentinel = object()
    monkeypatch.setattr(s, "_build_llm_call", lambda: sentinel)
    assert s.build_llm_call() is sentinel


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
<<<<<<< HEAD
        run_store=object(), graph_run_store=object(), project_scope_store=object()
=======
        run_store=object(),
        graph_run_store=object(),
        project_scope_store=object(),
        event_bus=object(),
>>>>>>> 0221d2cd799ec075e30c33e0b2e2fda573865aef
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
