"""#1181 — EngineService startup is atomic and health-visible.

Covers:
- singleton publication only after a fully successful start (no poisoned
  process-global after a failed boot)
- failure injected at each startup stage (agent-port binding, outcome store,
  metrics reset, DAG recovery, canonical recovery, task backend demo and
  production) → raise + deterministic unwind + `startup_failed` state +
  sanitized cause + unpublished singleton
- cancellation mid-boot (CancelledError is a BaseException) → same rollback +
  re-raise
- retry after the dependency is restored succeeds (documented policy:
  retryable, never terminal-poisoned)
- documented optional degradations (bridge→stub, capability wiring) reach
  `degraded` with a health-visible cause
- stop() terminal state; engine_health() answers for not_started, in-flight
  (`starting`, which /health/ready gates), failed, and published engines
- /health and /health/ready surfaces: engine field, degraded liveness,
  readiness 503 while a failed (or in-flight) engine gates the instance
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


class _Settings:
    """Stub/dev boot shape: no router key → StubAgentPort, production backend.

    The host-health attributes are the ones `wire_capabilities` reads off the
    config; without them a clean boot would degrade on capability wiring and
    the ready-state assertions below would lie.
    """

    maistro_router_api_key = ""
    maistro_base_url = "http://localhost:8000"
    hive_mode = "production"
    hive_default_workspace_id = "default"
    host_health_token = None
    host_health_url = ""
    infra_autonomy = "detect_only"


class _DemoSettings(_Settings):
    hive_mode = "demo"


@pytest.fixture(autouse=True)
def _reset_engine_globals():
    import services.engine as engine_mod
    from services import feedback_service

    prev_singleton = engine_mod._singleton
    prev_failed = engine_mod._failed_startup
    prev_setter = feedback_service.set_outcome_store
    seen: list[Any] = []
    # Direct assignment, never monkeypatch: a monkeypatch teardown may run
    # after this fixture's teardown and would then re-restore whatever it
    # recorded (None), re-poisoning the globals this fixture owns.
    engine_mod._singleton = None
    engine_mod._failed_startup = None
    engine_mod._booting = None
    feedback_service.set_outcome_store = seen.append
    yield
    engine_mod._singleton = prev_singleton
    engine_mod._failed_startup = prev_failed
    feedback_service.set_outcome_store = prev_setter


# --- failure at each startup stage ------------------------------------------


async def test_outcome_store_failure_rolls_back_and_stays_unpublished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The formerly unguarded middle: a raised step must fail the boot, not
    publish a half-wired singleton."""
    import services.canonical_recovery as canonical_recovery
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod
    from services import feedback_service

    def _boom(store: Any) -> None:
        raise RuntimeError("synthetic outcome store failure")

    feedback_service.set_outcome_store = _boom

    with pytest.raises(RuntimeError, match="synthetic outcome store failure"):
        await engine_mod.start_engine(_Settings())

    # Nothing after the failed step ran, and nothing is published.
    assert engine_mod._singleton is None
    assert dag_recovery._task is None
    assert canonical_recovery._task is None
    with pytest.raises(RuntimeError, match="EngineService not started"):
        engine_mod.get_engine()

    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"
    assert failed._agent_port is None
    assert failed._backend is None
    # The sanitized cause is type-qualified and carries the message.
    assert failed.health()["cause"] == "RuntimeError: synthetic outcome store failure"
    assert engine_mod.engine_health()["state"] == "startup_failed"


async def test_agent_port_binding_failure_is_a_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A port that does not satisfy AgentPort fails the boot at its first step."""
    import adapters.maistro_core as maistro_core
    import services.engine as engine_mod

    class _NotAPort:
        pass

    monkeypatch.setattr(maistro_core, "StubAgentPort", _NotAPort)

    with pytest.raises(TypeError, match="does not satisfy AgentPort"):
        await engine_mod.start_engine(_Settings())

    assert engine_mod._singleton is None
    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"
    assert failed._agent_port is None
    assert failed._backend is None
    assert (
        failed.health()["cause"]
        == "TypeError: _NotAPort does not satisfy AgentPort; the engine cannot route chat through it"
    )


async def test_metrics_reset_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.engine as engine_mod
    import services.node_metrics_store as node_metrics_store

    def _boom() -> None:
        raise RuntimeError("metrics buffer unavailable")

    monkeypatch.setattr(node_metrics_store, "reset_store", _boom)

    with pytest.raises(RuntimeError, match="metrics buffer unavailable"):
        await engine_mod.start_engine(_Settings())

    assert engine_mod._singleton is None
    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"
    assert failed._backend is None


async def test_dag_recovery_failure_fails_before_canonical_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_recovery as canonical_recovery
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod

    def _boom() -> None:
        raise RuntimeError("recovery loop refused")

    monkeypatch.setattr(dag_recovery, "start_dag_recovery", _boom)

    with pytest.raises(RuntimeError, match="recovery loop refused"):
        await engine_mod.start_engine(_Settings())

    assert engine_mod._singleton is None
    assert canonical_recovery._task is None, "later step never ran"
    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"


async def test_canonical_recovery_failure_unwinds_started_dag_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cadence that DID start before the failure is stopped again."""
    import services.canonical_recovery as canonical_recovery
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod

    def _boom() -> None:
        raise RuntimeError("canonical cadence refused")

    monkeypatch.setattr(canonical_recovery, "start_canonical_recovery", _boom)

    with pytest.raises(RuntimeError, match="canonical cadence refused"):
        await engine_mod.start_engine(_Settings())

    assert engine_mod._singleton is None
    assert dag_recovery._task is None, "started recovery cadence was unwound"
    assert engine_mod.engine_health()["cause"] == "RuntimeError: canonical cadence refused"


async def test_demo_backend_failure_unwinds_recovery_cadences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backend step follows the same contract (#1181): no chat-only engine
    whose dispatch is silently dead."""
    import types

    import services.canonical_recovery as canonical_recovery
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod

    stopped: list[bool] = []

    class _Runner:
        async def start(self) -> None:
            raise RuntimeError("runner refused")

        async def stop(self) -> None:
            stopped.append(True)

    class _Queue:
        def __init__(self, *, admitter: Any = None) -> None:
            self.admitter = admitter

    queue_mod = types.ModuleType("maistro.tasks.queue")
    queue_mod.TaskQueue = _Queue  # type: ignore[attr-defined]
    runner_mod = types.ModuleType("maistro.tasks.runner")
    runner_mod.TaskRunner = lambda queue, *, executor, attempts=None: _Runner()  # type: ignore[attr-defined,misc]
    monkeypatch.setitem(sys.modules, "maistro.tasks.queue", queue_mod)
    monkeypatch.setitem(sys.modules, "maistro.tasks.runner", runner_mod)
    conductor_mod = types.ModuleType("maistro.agents.conductor")

    async def _stub_run_task(*a: Any, **kw: Any) -> Any:
        return None

    conductor_mod.run_task = _stub_run_task  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.agents.conductor", conductor_mod)

    with pytest.raises(RuntimeError, match="runner refused"):
        await engine_mod.start_engine(_DemoSettings())

    assert engine_mod._singleton is None
    assert dag_recovery._task is None, "started recovery cadence was unwound"
    assert canonical_recovery._task is None, "started recovery cadence was unwound"
    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"
    assert failed._backend is None
    assert stopped == [True], "the half-started backend was stopped"


async def test_cancelled_boot_unwinds_cadences_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CancelledError derives from BaseException on every supported Python, so
    an `except Exception` rollback would never run for a lifespan task
    cancelled while awaiting a startup step: the recovery cadences would keep
    running and the instance would read `starting` forever. The rollback is
    driven by a BaseException guard; the cancellation itself is re-raised."""
    import asyncio
    import types

    import adapters.task_backend as task_backend
    import services.canonical_recovery as canonical_recovery
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod

    stopped: list[bool] = []
    reached_backend = asyncio.Event()

    class _NeverStartsBackend:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            reached_backend.set()
            await asyncio.Event().wait()  # cancelled while awaiting here

        async def stop(self) -> None:
            stopped.append(True)

    monkeypatch.setattr(task_backend, "LocalTaskBackend", _NeverStartsBackend)

    conductor_mod = types.ModuleType("maistro.agents.conductor")

    async def _stub_run_task(*a: Any, **kw: Any) -> Any:
        return None

    conductor_mod.run_task = _stub_run_task  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.agents.conductor", conductor_mod)

    boot = asyncio.create_task(engine_mod.start_engine(_DemoSettings()))
    await asyncio.wait_for(reached_backend.wait(), timeout=10)
    boot.cancel()
    with pytest.raises(asyncio.CancelledError):
        await boot

    # Same rollback contract as any raised failure: cadences stopped, handles
    # cleared, failed attempt retained for engine_health(), nothing published.
    assert engine_mod._singleton is None
    assert dag_recovery._task is None, "started recovery cadence was unwound"
    assert canonical_recovery._task is None, "started recovery cadence was unwound"
    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"
    assert failed._backend is None
    assert failed._agent_port is None
    assert stopped == [True], "the half-started backend was stopped"
    assert engine_mod.engine_health()["state"] == "startup_failed"


async def test_in_flight_boot_reports_starting_not_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-boot, `engine_health()` answers `starting` — the state ADR-100126-f9d6
    lists among the not-ready ones. With only the singleton/failed-attempt
    globals to look at, a slow dependency (DB reconnect, recovery cadences)
    read as the historical `not_started`, indistinguishable from a process
    that never tried to boot."""
    import asyncio
    import contextlib
    import types

    import adapters.task_backend as task_backend
    import services.engine as engine_mod

    reached_backend = asyncio.Event()

    class _SlowBackend:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def start(self) -> None:
            reached_backend.set()
            await asyncio.Event().wait()  # boot held mid-flight

        async def stop(self) -> None:
            pass

    monkeypatch.setattr(task_backend, "LocalTaskBackend", _SlowBackend)

    conductor_mod = types.ModuleType("maistro.agents.conductor")

    async def _stub_run_task(*a: Any, **kw: Any) -> Any:
        return None

    conductor_mod.run_task = _stub_run_task  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.agents.conductor", conductor_mod)

    boot = asyncio.create_task(engine_mod.start_engine(_DemoSettings()))
    try:
        await asyncio.wait_for(reached_backend.wait(), timeout=10)
        health = engine_mod.engine_health()
        assert health["state"] == "starting"
        assert health["cause"] is None
        assert engine_mod.engine_health()["task_backend"] is None
    finally:
        boot.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await boot
    # The in-flight marker never outlives the boot it described: the cancelled
    # attempt is retained as failed, and `starting` is gone.
    assert engine_mod.engine_health()["state"] == "startup_failed"


async def test_production_backend_failure_unwinds_recovery_cadences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import adapters.task_backend as task_backend
    import services.canonical_recovery as canonical_recovery
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod

    class _ExplodingBackend:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("remote task server unreachable")

    monkeypatch.setattr(task_backend, "MaistroServerTaskBackend", _ExplodingBackend)

    with pytest.raises(RuntimeError, match="remote task server unreachable"):
        await engine_mod.start_engine(_Settings())

    assert engine_mod._singleton is None
    assert dag_recovery._task is None
    assert canonical_recovery._task is None
    assert engine_mod.engine_health()["state"] == "startup_failed"


# --- retry semantics ---------------------------------------------------------


async def test_retry_after_dependency_restored_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documented policy (#1181): a failed first start is retryable, and the
    retry publishes only a fully started engine."""
    import services.engine as engine_mod
    from services import feedback_service

    def _boom(store: Any) -> None:
        raise RuntimeError("outcome store down")

    feedback_service.set_outcome_store = _boom
    with pytest.raises(RuntimeError, match="outcome store down"):
        await engine_mod.start_engine(_Settings())
    assert engine_mod._singleton is None
    assert engine_mod.engine_health()["state"] == "startup_failed"

    # Dependency restored: the next start_engine() boots a fresh engine.
    restored: list[Any] = []
    feedback_service.set_outcome_store = restored.append
    engine = await engine_mod.start_engine(_Settings())
    assert engine_mod._singleton is engine
    assert engine_mod._failed_startup is None
    assert engine.state == "ready"
    assert engine_mod.engine_health()["state"] == "ready"
    assert engine_mod.engine_health()["cause"] is None
    assert restored, "outcome store rebound on the successful retry"
    assert type(engine._backend).__name__ == "MaistroServerTaskBackend"

    # And shutdown is the truthful terminal state.
    await engine_mod.stop_engine()
    assert engine_mod._singleton is None
    assert engine.state == "stopped"
    with pytest.raises(RuntimeError, match="EngineService not started"):
        engine_mod.get_engine()


# --- documented optional degradations ----------------------------------------


async def test_started_bridge_container_is_aclosed_on_later_step_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured bridge that started, followed by a failed required step, is
    unwound by closing its Container — not by dropping the reference.

    `Container.aclose()` releases the pool lease / SQLite connections the
    container took; leaving them live on every retryable failure would exhaust
    database connection slots, and an abandoned aiosqlite worker (a
    non-daemon thread) could block process exit.
    """
    import adapters.maistro_core as maistro_core
    import services.dag_recovery as dag_recovery
    import services.engine as engine_mod
    from services import agent_materialization

    closed: list[bool] = []

    class _FakeContainer:
        async def aclose(self) -> None:
            closed.append(True)

    class _StartedBridge:
        def __init__(self) -> None:
            self.container: Any = None

        async def start(self, settings: Any) -> None:
            self.container = _FakeContainer()
            agent_materialization.register_runtime_source(
                container=self.container, llm=object(), preamble=""
            )

        async def route(self, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(maistro_core, "MaistroCoreBridge", _StartedBridge)

    def _boom() -> None:
        raise RuntimeError("dag cadence refused")

    monkeypatch.setattr(dag_recovery, "start_dag_recovery", _boom)

    class _Configured(_Settings):
        maistro_router_api_key = "router-key"

    with pytest.raises(RuntimeError, match="dag cadence refused"):
        await engine_mod.start_engine(_Configured())

    assert closed == [True], "the started bridge container was aclosed, not leaked"
    assert agent_materialization._runtime_source is None, (
        "the materialization seam was reset before the container went away"
    )
    failed = engine_mod._failed_startup
    assert failed is not None
    assert failed.state == "startup_failed"
    assert failed._agent_port is None


async def test_bridge_fallback_is_health_visible_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_mod
    from adapters.maistro_core import MaistroCoreBridge

    class _Configured(_Settings):
        maistro_router_api_key = "router-key"

    async def _fail_start(self: MaistroCoreBridge, settings: Any) -> None:
        del self, settings
        raise RuntimeError("synthetic bridge startup failure")

    monkeypatch.setattr(MaistroCoreBridge, "start", _fail_start)

    engine = await engine_mod.start_engine(_Configured())
    assert engine_mod._singleton is engine
    health = engine.health()
    assert health["state"] == "degraded"
    assert any(d.startswith("agent_port:") for d in health["degradations"])
    assert type(engine._agent_port).__name__ == "StubAgentPort"
    await engine_mod.stop_engine()


async def test_capability_wiring_failure_is_health_visible_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.capabilities_wiring as capabilities_wiring
    import services.engine as engine_mod

    def _boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("capability activation refused")

    monkeypatch.setattr(capabilities_wiring, "wire_capabilities", _boom)

    engine = await engine_mod.start_engine(_Settings())
    assert engine_mod._singleton is engine
    health = engine.health()
    assert health["state"] == "degraded"
    assert any(d.startswith("capabilities:") for d in health["degradations"])
    await engine_mod.stop_engine()


async def test_clean_boot_reports_ready() -> None:
    import services.engine as engine_mod

    engine = await engine_mod.start_engine(_Settings())
    assert engine.state == "ready"
    health = engine.health()
    assert health["state"] == "ready"
    assert health["cause"] is None
    assert health["degradations"] == []
    await engine_mod.stop_engine()
    assert engine.state == "stopped"


# --- engine_health() surface --------------------------------------------------


def test_engine_health_answers_when_never_started() -> None:
    import services.engine as engine_mod

    health = engine_mod.engine_health()
    assert health["state"] == "not_started"
    assert health["cause"] is None
    assert health["degradations"] == []
    assert health["agent_port"] is None
    assert health["task_backend"] is None


def test_engine_health_prefers_the_published_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_mod

    published = engine_mod.EngineService()
    published._state = "ready"
    failed = engine_mod.EngineService()
    failed._state = "startup_failed"
    failed._startup_error = "RuntimeError: boom"
    engine_mod._singleton = published
    engine_mod._failed_startup = failed

    assert engine_mod.engine_health()["state"] == "ready"

    monkeypatch.setattr(engine_mod, "_singleton", None)
    assert engine_mod.engine_health()["state"] == "startup_failed"


def test_sanitize_cause_is_bounded() -> None:
    from services.engine import _sanitize_cause

    class _Long(RuntimeError):
        def __str__(self) -> str:
            return "x" * 5000

    cause = _sanitize_cause(_Long())
    assert cause.startswith("_Long: ")
    assert len(cause) < 400


def test_sanitize_cause_redacts_credentials_before_truncation() -> None:
    """Startup dependency errors hit the unauthenticated /health as `cause`
    or inside `degradations`, so the message body is passed through the
    ADR-064 redactor — truncation alone would publish whatever credential
    the dependency interpolated into its exception text (review on #1181)."""
    from services.engine import _sanitize_cause

    dsn = RuntimeError("could not connect to postgresql://ops:s3cr3t-Pa1nt@db.internal:5432/hive")
    cause = _sanitize_cause(dsn)
    assert "s3cr3t-Pa1nt" not in cause
    assert "REDACTED" in cause  # marker proves the redactor ran, not truncation

    token = RuntimeError("auth rejected: Bearer sk-abcdef0123456789abcdef")
    assert "sk-abcdef0123456789abcdef" not in _sanitize_cause(token)


def test_sanitize_cause_fails_closed_without_the_redactor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the redactor cannot be imported, only the exception type is
    published — never an unvetted message body."""
    import builtins

    from services.engine import _sanitize_cause

    real_import = builtins.__import__

    def _no_redactor(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "maistro.security.redact":
            raise ImportError("simulated redactor unavailability")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_redactor)
    assert _sanitize_cause(RuntimeError("jdbc:postgres://u:p@h/x")) == "RuntimeError"


# --- /health and /health/ready surfaces ---------------------------------------


def _client() -> Any:
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def test_health_ready_gates_on_failed_engine_start() -> None:
    """A boot that failed takes the instance out of rotation (#1181): /health
    names the state and sanitized cause; /health/ready answers 503."""
    import services.engine as engine_mod

    failed = engine_mod.EngineService()
    failed._state = "startup_failed"
    failed._startup_error = "RuntimeError: canonical cadence refused"
    engine_mod._singleton = None
    engine_mod._failed_startup = failed

    client = _client()
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    body = ready.json()
    assert body["ready"] is False
    assert body["checks"]["engine"] is False

    live = client.get("/health").json()
    assert live["engine"]["state"] == "startup_failed"
    assert live["engine"]["cause"] == "RuntimeError: canonical cadence refused"
    assert live["degraded"] is True
    # Liveness stays liveness: a failed engine is not an outage signal.
    assert live["status"] == "ok"


def test_health_ready_ignores_never_attempted_engine() -> None:
    """Contexts that never run the app lifespan (tests, scripts) keep the
    historical readiness contract; a missing engine is not a failed one."""
    import services.engine as engine_mod

    engine_mod._singleton = None
    engine_mod._failed_startup = None
    engine_mod._booting = None

    client = _client()
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["ready"] is True
    assert body["checks"]["engine"] is True

    live = client.get("/health").json()
    assert live["engine"]["state"] == "not_started"


def test_health_ready_gates_on_in_flight_boot() -> None:
    """ADR-100126-f9d6 lists `starting` among the not-ready states: a boot held
    mid-flight takes the instance out of rotation instead of answering the
    historical 200 that `not_started` alone keeps for never-booted contexts."""
    import services.engine as engine_mod

    booting = engine_mod.EngineService()
    booting._state = "starting"
    engine_mod._singleton = None
    engine_mod._failed_startup = None
    engine_mod._booting = booting

    client = _client()
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    body = ready.json()
    assert body["ready"] is False
    assert body["checks"]["engine"] is False

    live = client.get("/health").json()
    assert live["engine"]["state"] == "starting"
    # Mid-boot there is no failure to report yet: no sanitized cause, and the
    # engine state alone must not flip the aggregate `degraded` flag
    # ("starting" is absent from its state set — the other disjuncts belong
    # to other subsystems).
    assert live["engine"]["cause"] is None
    assert live["status"] == "ok"


def test_health_reports_degraded_engine_state() -> None:
    """A serving engine with an optional-component failure shows in liveness."""
    import services.engine as engine_mod

    engine = engine_mod.EngineService()
    engine._state = "degraded"
    engine._degradations = ["agent_port: RuntimeError: synthetic bridge failure"]
    engine_mod._singleton = engine
    engine_mod._failed_startup = None

    live = _client().get("/health").json()
    assert live["engine"]["state"] == "degraded"
    assert live["degraded"] is True
    assert _client().get("/health/ready").json()["checks"]["engine"] is True


def test_health_survives_engine_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defensive contract every /health probe holds: a broken probe is
    reported, never a 500 — and it never reads as ready."""
    import services.engine as engine_mod

    def _broken() -> dict[str, Any]:
        raise RuntimeError("engine probe exploded")

    monkeypatch.setattr(engine_mod, "engine_health", _broken)

    client = _client()
    live = client.get("/health")
    assert live.status_code == 200
    assert live.json()["engine"]["state"] == "unknown"
    assert live.json()["engine"]["cause"] == "health_probe_failed"
    # Liveness and readiness must agree that something is wrong: an unreadable
    # engine probe degrades the liveness body instead of reading as healthy
    # while /health/ready returns 503.
    assert live.json()["degraded"] is True
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["engine"] is False
