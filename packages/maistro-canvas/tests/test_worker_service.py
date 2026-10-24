"""The shipped Canvas worker service (#93): configuration and process shape.

``CanvasJobRunner``'s queue mechanics have their own suites; this one covers
the deployment surface that makes the worker a *supported* component instead
of an ad-hoc script:

- the environment fully describes a startable worker, and every missing or
  malformed piece fails startup with an error naming the variable — never a
  half-wired runner claiming jobs it cannot execute;
- ``module:attr`` adapter targets resolve to instances/classes/zero-arg
  factories (including async ones), and unresolvable targets are config
  errors, not first-claim crashes;
- the worker refuses an unmigrated database up front instead of silently
  falling back to an in-memory spine that cannot see the HTTP process's
  admitted Runs;
- the production composition path builds the runner through
  ``build_canvas_runtime`` — the seam that makes a runner without the
  canonical Run/NodeRun/Attempt binding unrepresentable — with the resolved
  adapters, scope, and concurrency;
- ``run_worker`` starts the composed runner, wakes on the stop signal *or*
  runner death, stops gracefully, and closes every resource it opened; a
  runner that dies mid-flight fails the service (exit 1) rather than
  reporting a clean stop.

Postgres-backed legs are deliberately out of scope here: the queue semantics
against a real server are covered by ``test_store_scope_conformance.py`` and
``test_migration_parity.py``. This suite proves the service is wired honestly
using the same in-memory substitutes the runner suites use.
"""

from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

import maistro_canvas.canvas.worker_service as worker_service
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro_canvas.canvas.composition import CanvasRuntime, build_canvas_runtime
from maistro_canvas.canvas.worker_service import (
    CanvasWorkerSettings,
    WorkerConfigError,
    assert_database_migrated,
    compose_runtime,
    load_env_file,
    resolve_target,
    run_worker,
)

# ─────────────────────────────────────────────────────────────────────
# Adapter stubs addressable as module:attr targets via this test module
# ─────────────────────────────────────────────────────────────────────


class _StubImageClient:
    async def generate(self, **_kwargs: object) -> list[Any]:
        return []

    async def refine(self, **_kwargs: object) -> list[Any]:
        return []

    async def list_image_models(self) -> list[Any]:
        return []


class _StubRegistry:
    def is_registered(self, _model_id: str) -> bool:
        return True

    def get_default_draft(self) -> str:
        return "draft-model"


class _StubWarden:
    async def scan_prompt(self, prompt: str) -> str:
        return prompt


#: Instance-form target (used as-is, never constructed).
_RESOLVED_IMAGE_CLIENT = _StubImageClient()


def _image_client_factory() -> _StubImageClient:
    return _StubImageClient()


async def _image_client_async_factory() -> _StubImageClient:
    await asyncio.sleep(0)
    return _StubImageClient()


class _GenerateOnlyImageClient:
    """Resolves, but lacks the ``refine`` method the executor awaits."""

    async def generate(self, **_kwargs: object) -> list[Any]:
        return []


def _none_image_client_factory() -> None:
    """A target that resolves successfully to ``None``."""
    return None


# ─────────────────────────────────────────────────────────────────────
# Environment parsing
# ─────────────────────────────────────────────────────────────────────

_REQUIRED_VARS = {
    "MAISTRO_CANVAS_PG_DSN": "postgresql://user:pass@db:5432/canvas",
    "MAISTRO_CANVAS_WORKSPACE_ID": "workspace-1",
    "MAISTRO_CANVAS_PROJECT_ID": "project-1",
    "MAISTRO_CANVAS_IMAGE_CLIENT": f"{__name__}:_RESOLVED_IMAGE_CLIENT",
    "MAISTRO_CANVAS_MODEL_REGISTRY": f"{__name__}:_StubRegistry",
    "MAISTRO_CANVAS_WARDEN": f"{__name__}:_StubWarden",
}

_TUNING_VARS = (
    "MAISTRO_CANVAS_WORKER_ID",
    "MAISTRO_CANVAS_LEASE_SECONDS",
    "MAISTRO_CANVAS_POLL_INTERVAL",
    "MAISTRO_CANVAS_REAP_INTERVAL",
    "MAISTRO_CANVAS_MAX_EXECUTION_SECONDS",
    "MAISTRO_CANVAS_CONCURRENCY",
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(_REQUIRED_VARS) + list(_TUNING_VARS):
        monkeypatch.delenv(name, raising=False)


def _set_required_env(monkeypatch: pytest.MonkeyPatch, *, skip: str | None = None) -> None:
    for name, value in _REQUIRED_VARS.items():
        if name != skip:
            monkeypatch.setenv(name, value)


def test_from_env_requires_every_critical_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    for name in _REQUIRED_VARS:
        # Absent-first: earlier iterations may have set this var; the one
        # under test must be gone before from_env runs.
        monkeypatch.delenv(name, raising=False)
        _set_required_env(monkeypatch, skip=name)
        with pytest.raises(WorkerConfigError, match=name):
            CanvasWorkerSettings.from_env()


def test_from_env_parses_full_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MAISTRO_CANVAS_WORKER_ID", "canvas-worker-a")
    monkeypatch.setenv("MAISTRO_CANVAS_LEASE_SECONDS", "120")
    monkeypatch.setenv("MAISTRO_CANVAS_POLL_INTERVAL", "0.5")
    monkeypatch.setenv("MAISTRO_CANVAS_CONCURRENCY", "3")

    settings = CanvasWorkerSettings.from_env()
    assert settings.pg_dsn == "postgresql://user:pass@db:5432/canvas"
    assert settings.workspace_id == "workspace-1"
    assert settings.project_id == "project-1"
    assert settings.worker_id == "canvas-worker-a"
    assert settings.lease_seconds == 120
    assert settings.poll_interval == 0.5
    assert settings.concurrency == 3
    assert settings.max_execution_seconds == 1800.0  # documented default


def test_from_env_derives_a_host_pid_worker_id_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_env(monkeypatch)
    _set_required_env(monkeypatch)
    settings = CanvasWorkerSettings.from_env()
    assert settings.worker_id.startswith("canvas-worker-")
    assert socket.gethostname() in settings.worker_id
    assert str(os.getpid()) in settings.worker_id


def test_from_env_rejects_invalid_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MAISTRO_CANVAS_POLL_INTERVAL", "soon")
    with pytest.raises(WorkerConfigError, match="MAISTRO_CANVAS_POLL_INTERVAL"):
        CanvasWorkerSettings.from_env()
    monkeypatch.setenv("MAISTRO_CANVAS_POLL_INTERVAL", "-1")
    with pytest.raises(WorkerConfigError, match="positive"):
        CanvasWorkerSettings.from_env()
    monkeypatch.delenv("MAISTRO_CANVAS_POLL_INTERVAL", raising=False)
    monkeypatch.setenv("MAISTRO_CANVAS_CONCURRENCY", "0")
    with pytest.raises(WorkerConfigError, match="at least 1"):
        CanvasWorkerSettings.from_env()


# ─────────────────────────────────────────────────────────────────────
# Adapter target resolution
# ─────────────────────────────────────────────────────────────────────


async def test_resolve_target_accepts_instance_class_factory_and_async_factory() -> None:
    instance = await resolve_target(f"{__name__}:_RESOLVED_IMAGE_CLIENT")
    assert isinstance(instance, _StubImageClient)

    from_class = await resolve_target(f"{__name__}:_StubRegistry")
    assert isinstance(from_class, _StubRegistry)

    from_factory = await resolve_target(f"{__name__}:_image_client_factory")
    assert isinstance(from_factory, _StubImageClient)

    from_async_factory = await resolve_target(f"{__name__}:_image_client_async_factory")
    assert isinstance(from_async_factory, _StubImageClient)


async def test_resolve_target_fails_loudly_on_bad_targets() -> None:
    for bad in ("no-colon-at-all", "definitely_not_a_module_xyz:Thing", "os:no_such_attr_xyz"):
        with pytest.raises(WorkerConfigError):
            await resolve_target(bad)


# ─────────────────────────────────────────────────────────────────────
# Migration preflight
# ─────────────────────────────────────────────────────────────────────


class _FakePool:
    def __init__(self, existing: set[str] | None = None) -> None:
        self._existing = existing if existing is not None else set(worker_service._REQUIRED_TABLES)
        self.closed = False

    async def fetchval(self, _query: str, name: str) -> bool:
        return name.removeprefix("public.") in self._existing

    async def close(self) -> None:
        self.closed = True


async def test_refuses_unmigrated_database_naming_the_fix() -> None:
    pool = _FakePool(
        set(worker_service._REQUIRED_TABLES) - {"generation_jobs", "canonical_attempts"}
    )
    with pytest.raises(WorkerConfigError, match="alembic upgrade head"):
        await assert_database_migrated(pool)
    assert pool.closed is False  # preflight reports; it does not close


async def test_preflight_passes_when_every_table_exists() -> None:
    await assert_database_migrated(_FakePool())


# ─────────────────────────────────────────────────────────────────────
# Production composition path
# ─────────────────────────────────────────────────────────────────────


def _settings() -> CanvasWorkerSettings:
    return CanvasWorkerSettings(
        pg_dsn="postgresql://user:pass@db:5432/canvas",
        workspace_id="workspace-1",
        project_id="project-1",
        worker_id="canvas-worker-test",
        image_client_target=f"{__name__}:_RESOLVED_IMAGE_CLIENT",
        model_registry_target=f"{__name__}:_StubRegistry",
        warden_target=f"{__name__}:_StubWarden",
        concurrency=2,
    )


async def test_compose_runtime_builds_the_canonical_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entrypoint may not assemble a runner outside build_canvas_runtime."""
    pool = _FakePool()
    engines: list[Any] = []
    engine_dsns: list[str] = []

    async def fake_create_pool(*, dsn: str) -> Any:
        # asyncpg takes the plain URL; the driver qualification is SQLAlchemy's.
        assert dsn == "postgresql://user:pass@db:5432/canvas"
        return pool

    wired_run_stores: list[Any] = []

    async def fake_wire_execution_spine(_conn: Any, **kwargs: Any) -> tuple[Any, ...]:
        # The worker is a consumer: it must not prime authorization scope.
        assert kwargs["prime"] is False
        assert kwargs["workspace_id"] == "workspace-1"
        assert kwargs["pg_pool"] is pool
        scope = InMemoryProjectScopeStore()
        store = InMemoryRunStore(project_store=scope)
        wired_run_stores.append(store)
        return (scope, store, object(), object(), object(), object())

    class _FakeEngine:
        async def dispose(self) -> None:
            engines.append(self)

    def fake_create_engine(dsn: str) -> Any:
        engine_dsns.append(dsn)
        return _FakeEngine()

    monkeypatch.setattr("asyncpg.create_pool", fake_create_pool)
    monkeypatch.setattr("maistro.runs.wiring.wire_execution_spine", fake_wire_execution_spine)
    monkeypatch.setattr(worker_service, "create_async_engine", fake_create_engine)

    runtime, returned_pool, engine = await compose_runtime(_settings())

    assert returned_pool is pool
    assert isinstance(engine, _FakeEngine)
    # SQLAlchemy resolves a bare postgresql:// URL to psycopg2, which this
    # service does not depend on: the engine must get the asyncpg-qualified
    # URL while the asyncpg pool keeps the plain one.
    assert engine_dsns == ["postgresql+asyncpg://user:pass@db:5432/canvas"]
    # The composed runtime is canonically bound: the executor admits Runs and
    # the runner refuses the compatibility-only non-canonical path.
    assert runtime.executor.canonical_enabled is True
    assert runtime.canonical_execution._runs is wired_run_stores[0]
    assert runtime.canonical_execution._workspace_id == "workspace-1"
    assert runtime.canonical_execution._project_id == "project-1"
    assert runtime.runner._worker_id == "canvas-worker-test"
    assert runtime.runner._concurrency == 2


async def test_compose_runtime_rejects_adapters_the_executor_cannot_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolved adapter missing an executor method must fail at startup.

    ``resolve_target`` accepts whatever a factory returns, including ``None``.
    Composing past that would let the worker claim a job and only then fail
    the provider call inside it — spending the job's retry budget and
    terminalizing its canonical Run as failed. The guard turns the mismatch
    into a :class:`WorkerConfigError` before any claim.
    """
    pool = _FakePool()

    async def fake_create_pool(*, dsn: str) -> Any:
        return pool

    async def fake_wire_execution_spine(_conn: Any, **kwargs: Any) -> tuple[Any, ...]:
        scope = InMemoryProjectScopeStore()
        store = InMemoryRunStore(project_store=scope)
        return (scope, store, object(), object(), object(), object())

    class _FakeEngine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr("asyncpg.create_pool", fake_create_pool)
    monkeypatch.setattr("maistro.runs.wiring.wire_execution_spine", fake_wire_execution_spine)
    monkeypatch.setattr(worker_service, "create_async_engine", lambda _dsn: _FakeEngine())

    with pytest.raises(WorkerConfigError, match="refine"):
        await compose_runtime(
            replace(_settings(), image_client_target=f"{__name__}:_GenerateOnlyImageClient")
        )
    with pytest.raises(WorkerConfigError, match="generate"):
        await compose_runtime(
            replace(_settings(), image_client_target=f"{__name__}:_none_image_client_factory")
        )
    with pytest.raises(WorkerConfigError, match="scan_prompt"):
        await compose_runtime(
            replace(_settings(), warden_target=f"{__name__}:_GenerateOnlyImageClient")
        )


# ─────────────────────────────────────────────────────────────────────
# Service lifecycle
# ─────────────────────────────────────────────────────────────────────


class _SpyRunner:
    """Wraps the real runner to observe the service actually driving it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True
        await self._inner.start()

    def stop(self) -> None:
        self.stopped = True
        self._inner.stop()


class _EmptyStore:
    """An idle queue: claims return nothing, so the loop idles cleanly."""

    async def claim_next_pending(self, _worker_id: str, _lease_seconds: int) -> None:
        return None


async def _build_runtime_with_spy(worker_id: str = "canvas-worker-test") -> tuple[Any, _SpyRunner]:
    projects = InMemoryProjectScopeStore()
    run_store = InMemoryRunStore(project_store=projects)
    runtime = build_canvas_runtime(
        store=_EmptyStore(),  # type: ignore[arg-type]
        image_client=_StubImageClient(),  # type: ignore[arg-type]
        model_registry=_StubRegistry(),  # type: ignore[arg-type]
        warden=_StubWarden(),  # type: ignore[arg-type]
        run_store=run_store,
        workspace_id="workspace-1",
        project_id="project-1",
        worker_id=worker_id,
        poll_interval=0.001,
    )
    spy = _SpyRunner(runtime.runner)
    composed = CanvasRuntime(
        store=runtime.store,
        canonical_execution=runtime.canonical_execution,
        executor=runtime.executor,
        runner=spy,
    )
    return composed, spy


async def test_run_worker_starts_runner_and_stops_gracefully() -> None:
    composed, spy = await _build_runtime_with_spy()
    pool = _FakePool()
    disposed: list[bool] = []

    class _Engine:
        async def dispose(self) -> None:
            disposed.append(True)

    factory_calls: list[CanvasWorkerSettings] = []

    def factory(settings: CanvasWorkerSettings) -> tuple[Any, Any, Any]:
        factory_calls.append(settings)
        return composed, pool, _Engine()

    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)

    exit_code = await run_worker(
        _settings(),  # type: ignore[arg-type]
        runtime_factory=factory,
        stop_event=stop_event,
    )

    assert exit_code == 0
    assert factory_calls and factory_calls[0].worker_id == "canvas-worker-test"
    assert spy.started, "the service never started the composed runner"
    assert spy.stopped, "the service never asked the runner to stop"
    assert pool.closed, "the asyncpg pool was not closed on shutdown"
    assert disposed == [True]


async def test_run_worker_exits_nonzero_when_the_runner_dies() -> None:
    """A runner that crashes mid-flight fails the service — no fake clean stop."""

    class _DeadRunner:
        async def start(self) -> None:
            raise RuntimeError("runner exploded")

        def stop(self) -> None:
            return None

    composed = SimpleNamespace(runner=_DeadRunner())
    pool = _FakePool()

    class _Engine:
        async def dispose(self) -> None:
            return None

    exit_code = await run_worker(
        _settings(),  # type: ignore[arg-type]
        runtime_factory=lambda _settings: (composed, pool, _Engine()),
        stop_event=asyncio.Event(),
    )
    assert exit_code == 1
    assert pool.closed, "resources are released even after a runner crash"


async def test_run_worker_shutdown_survives_cancellation_suppressing_runner() -> None:
    """A runner that swallows ``CancelledError`` cannot hang shutdown.

    Mirrors the bound in ``bind_canvas_runner_lifecycle``: after cancelling,
    the service waits one more bounded grace window and then abandons the
    stuck task (with an error log), still reaching pool/engine cleanup (the
    unbounded ``gather`` here would never return — Codex review, #93).
    """

    class _StuckRunner:
        def __init__(self) -> None:
            self.stopped = False

        async def start(self) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # The pathological case: suppress cancellation and stall.
                await asyncio.sleep(3600)

        def stop(self) -> None:
            self.stopped = True

    runner = _StuckRunner()
    composed = SimpleNamespace(runner=runner)
    pool = _FakePool()

    class _Engine:
        async def dispose(self) -> None:
            return None

    stop_event = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop_event.set)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(worker_service, "_SHUTDOWN_GRACE_SECONDS", 0.05)
        exit_code = await asyncio.wait_for(
            run_worker(
                _settings(),  # type: ignore[arg-type]
                runtime_factory=lambda _settings: (composed, pool, _Engine()),
                stop_event=stop_event,
            ),
            timeout=10,
        )

    assert exit_code == 0
    assert pool.closed, "the bounded wait lets shutdown reach resource cleanup"


# ─────────────────────────────────────────────────────────────────────
# Console entry point
# ─────────────────────────────────────────────────────────────────────


def test_main_reports_config_error_as_exit_two(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    assert worker_service.main() == 2


def test_main_reports_runner_crash_as_exit_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _clean_env(monkeypatch)
    _set_required_env(monkeypatch)

    async def exploding_worker(_settings: CanvasWorkerSettings, **_kwargs: Any) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_service, "run_worker", exploding_worker)
    with caplog.at_level("ERROR", logger="maistro.canvas.worker_service"):
        assert worker_service.main() == 1
    assert any("canvas_worker_crashed" in record.getMessage() for record in caplog.records)


def test_load_env_file_parses_comments_and_rejects_malformed_lines(tmp_path: Any) -> None:
    env_file = tmp_path / "worker.env"
    env_file.write_text(
        "# canvas worker\nMAISTRO_CANVAS_PG_DSN=postgresql://db/canvas\n",
        encoding="utf-8",
    )
    values = load_env_file(env_file)
    assert values == {"MAISTRO_CANVAS_PG_DSN": "postgresql://db/canvas"}

    broken = tmp_path / "broken.env"
    broken.write_text("NO_SEPARATOR\n", encoding="utf-8")
    with pytest.raises(WorkerConfigError, match="KEY=VALUE"):
        load_env_file(broken)
