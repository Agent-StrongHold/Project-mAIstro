"""The shipped built-in Canvas worker service (#93, SPEC-203).

``CanvasJobRunner`` is the execution mechanic; this module is the *deployment*
shape that makes it a supported component rather than an ad-hoc script: one
console-script process, configured entirely through the environment, that
claims and drives Canvas generation jobs against the same durable store the
HTTP boundary writes to. A supported deployment runs this service (compose
service, systemd unit, Kubernetes Deployment) — jobs then advance with no
external runner and no browser open, and several replicas may run at once
(claims are atomic and every terminal write is fenced, so replicas never
double-process one physical job).

Configuration (environment):

- ``MAISTRO_CANVAS_PG_DSN`` (required) — PostgreSQL DSN. Both the Canvas
  queue and the canonical Run spine are read/written here; the worker refuses
  to start against an unmigrated database rather than silently working on an
  in-memory spine that cannot see the routes' admitted Runs.
- ``MAISTRO_CANVAS_WORKSPACE_ID`` (required) — the canonical scope binding
  for execution. Like every ``CanvasCanonicalExecution`` scope, it must come
  from the deployment's own authorization path; the worker never derives it
  from canvas/org ids.
- ``MAISTRO_CANVAS_PROJECT_ID`` (required) — the Project the admitted Runs
  file under.
- ``MAISTRO_CANVAS_IMAGE_CLIENT`` / ``MAISTRO_CANVAS_MODEL_REGISTRY`` /
  ``MAISTRO_CANVAS_WARDEN`` (required) — ``module:attr`` targets resolving to
  the deployment's provider adapters (``ImageGenClient``, the model
  registry, and the prompt warden). Canvas deliberately ships no built-in
  image provider; a worker that cannot name its adapters refuses to start
  instead of claiming jobs it cannot execute.
- ``MAISTRO_CANVAS_WORKER_ID`` (optional) — defaults to
  ``canvas-worker-<host>-<pid>``. Distinct per process is for readable logs;
  correctness never relies on it (writes fence on the claim's attempt
  generation, not the id).
- ``MAISTRO_CANVAS_LEASE_SECONDS`` (300), ``MAISTRO_CANVAS_POLL_INTERVAL``
  (1.0), ``MAISTRO_CANVAS_REAP_INTERVAL`` (30.0),
  ``MAISTRO_CANVAS_MAX_EXECUTION_SECONDS`` (1800.0) and
  ``MAISTRO_CANVAS_CONCURRENCY`` (1) — runner tuning; see
  ``CanvasJobRunner``.

Exit codes: ``0`` clean shutdown, ``2`` configuration error (missing env var,
unresolvable adapter target, unmigrated database), ``1`` unexpected crash.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
import signal
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from inspect import isawaitable
from os import PathLike
from typing import Any, cast

from sqlalchemy.ext.asyncio import create_async_engine

from maistro_canvas.canvas.composition import CanvasRuntime, build_canvas_runtime
from maistro_canvas.canvas.store import PgCanvasStore

logger = logging.getLogger("maistro.canvas.worker_service")

_DEFAULT_LEASE_SECONDS = 300
_DEFAULT_POLL_INTERVAL = 1.0
_DEFAULT_REAP_INTERVAL = 30.0
_DEFAULT_MAX_EXECUTION_SECONDS = 1800.0
_DEFAULT_CONCURRENCY = 1

_SHUTDOWN_GRACE_SECONDS = 10.0

#: Tables the worker needs before it may claim anything: the canonical spine
#: (same list ``maistro.runs.wiring`` probes) plus the Canvas queue tables the
#: root alembic chain owns (044_canvas_store_tables). Missing either means
#: `alembic upgrade head` has not run against this database.
_REQUIRED_TABLES = (
    "canonical_projects",
    "canonical_runs",
    "canonical_node_runs",
    "canonical_attempts",
    "graph_templates",
    "canvases",
    "layers",
    "generation_jobs",
)


class WorkerConfigError(RuntimeError):
    """The environment does not describe a startable worker."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise WorkerConfigError(f"{name} is required to run the Canvas worker service")
    return value


def _optional_number(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise WorkerConfigError(f"{name}={raw!r} is not a number") from None
    if value <= 0:
        raise WorkerConfigError(f"{name} must be positive, got {value}")
    return value


def _optional_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise WorkerConfigError(f"{name}={raw!r} is not an integer") from None
    if value < 1:
        raise WorkerConfigError(f"{name} must be at least 1, got {value}")
    return value


@dataclass(frozen=True)
class CanvasWorkerSettings:
    """Fully-resolved worker configuration (no env access after construction)."""

    pg_dsn: str
    workspace_id: str
    project_id: str
    worker_id: str
    image_client_target: str
    model_registry_target: str
    warden_target: str
    lease_seconds: int = _DEFAULT_LEASE_SECONDS
    poll_interval: float = _DEFAULT_POLL_INTERVAL
    reap_interval: float = _DEFAULT_REAP_INTERVAL
    max_execution_seconds: float = _DEFAULT_MAX_EXECUTION_SECONDS
    concurrency: int = _DEFAULT_CONCURRENCY

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> CanvasWorkerSettings:
        """Parse and validate the environment into settings.

        Every problem is reported as a :class:`WorkerConfigError` naming the
        offending variable — a supported deployment must fail visibly at
        startup, never claim jobs with a half-wired execution path.
        """
        env = os.environ if env is None else env
        return cls(
            pg_dsn=_required(env, "MAISTRO_CANVAS_PG_DSN"),
            workspace_id=_required(env, "MAISTRO_CANVAS_WORKSPACE_ID"),
            project_id=_required(env, "MAISTRO_CANVAS_PROJECT_ID"),
            worker_id=env.get("MAISTRO_CANVAS_WORKER_ID", "").strip()
            or f"canvas-worker-{socket.gethostname()}-{os.getpid()}",
            image_client_target=_required(env, "MAISTRO_CANVAS_IMAGE_CLIENT"),
            model_registry_target=_required(env, "MAISTRO_CANVAS_MODEL_REGISTRY"),
            warden_target=_required(env, "MAISTRO_CANVAS_WARDEN"),
            lease_seconds=int(
                _optional_number(env, "MAISTRO_CANVAS_LEASE_SECONDS", _DEFAULT_LEASE_SECONDS)
            ),
            poll_interval=_optional_number(
                env, "MAISTRO_CANVAS_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL
            ),
            reap_interval=_optional_number(
                env, "MAISTRO_CANVAS_REAP_INTERVAL", _DEFAULT_REAP_INTERVAL
            ),
            max_execution_seconds=_optional_number(
                env, "MAISTRO_CANVAS_MAX_EXECUTION_SECONDS", _DEFAULT_MAX_EXECUTION_SECONDS
            ),
            concurrency=_optional_int(env, "MAISTRO_CANVAS_CONCURRENCY", _DEFAULT_CONCURRENCY),
        )


async def resolve_target(target: str) -> Any:
    """Resolve a ``module:attr`` config target to a ready adapter instance.

    The attribute may be an adapter instance (used as-is), a class
    (instantiated without arguments) or a zero-argument factory (called; an
    awaitable result is awaited). Anything else — or an unresolvable target —
    is a :class:`WorkerConfigError`, so a typo'd env var fails at startup
    rather than on the first claimed job.
    """
    module_name, separator, attr_name = target.partition(":")
    if not separator or not module_name or not attr_name:
        raise WorkerConfigError(
            f"adapter target {target!r} must be 'module:attribute' (e.g. 'myorg.adapters:ImageClient')"
        )
    try:
        module = importlib.import_module(module_name)
        attribute = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise WorkerConfigError(f"adapter target {target!r} does not resolve: {exc}") from exc
    if isinstance(attribute, type) or callable(attribute):
        attribute = attribute()
    if asyncio.iscoroutine(attribute):
        # A zero-arg factory may build the adapter asynchronously (e.g. an
        # HTTP client); resolve it here, at startup, on the worker's loop.
        attribute = await attribute
    return attribute


async def assert_database_migrated(pool: Any) -> None:
    """Refuse to start against a database missing the tables the worker needs.

    ``wire_execution_spine`` falls back to an in-memory spine when the pool's
    database is unmigrated — the right behavior for an app server, and exactly
    wrong for a worker: an in-memory spine cannot see the Runs the HTTP
    process admitted, so every claim would fail against an empty world while
    looking healthy. The worker probes up front and refuses instead.

    The pool needs exactly one asyncpg surface: ``fetchval`` (each probe is a
    scalar ``SELECT to_regclass($1) IS NOT NULL``), so any asyncpg-compatible
    pool works — tests substitute an in-memory double.
    """
    missing: list[str] = []
    for table in _REQUIRED_TABLES:
        present = await pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
        if not present:
            missing.append(table)
    if missing:
        raise WorkerConfigError(
            "database is missing required tables ("
            + ", ".join(missing)
            + "); run `alembic upgrade head` against MAISTRO_CANVAS_PG_DSN before starting the worker"
        )


def sqlalchemy_asyncpg_url(dsn: str) -> str:
    """Spell the driver ``create_async_engine`` must use into the DSN.

    Operators write the ordinary ``postgresql://user:pass@host/db`` form — the
    same string ``asyncpg.create_pool`` takes above. SQLAlchemy resolves that
    bare scheme to psycopg2, which this service deliberately does not depend
    on, so an unqualified URL is rewritten to ``postgresql+asyncpg://``; an
    already driver-qualified URL passes through untouched. Found live: the
    first real start against a migrated database crashed in engine creation,
    not in any queue logic (#93).
    """
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "sqlite+aiosqlite://"):
        if dsn.startswith(prefix):
            return dsn
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return f"postgresql+asyncpg://{dsn[len(prefix) :]}"
    return dsn


def _require_adapter_methods(target: str, adapter: Any, *names: str) -> Any:
    """Assert a resolved adapter exposes the callables its consumer awaits.

    ``resolve_target`` accepts whatever the target returns, including a
    factory's ``None``. An adapter missing a required method would otherwise
    pass composition and fail only inside a claimed job, spending that job's
    retry budget and terminalizing its canonical Run as failed. Checked here
    so the mismatch is a :class:`WorkerConfigError` at startup instead.
    """
    for name in names:
        if not callable(getattr(adapter, name, None)):
            raise WorkerConfigError(
                f"adapter target {target!r} resolved to {type(adapter).__name__!r}, "
                f"which lacks a callable {name!r} method required by the Canvas worker"
            )
    return adapter


async def compose_runtime(settings: CanvasWorkerSettings) -> tuple[CanvasRuntime, Any, Any]:
    """Build the canonical Canvas runtime from resolved settings.

    Returns the runtime plus the asyncpg pool and SQLAlchemy engine it was
    built over, so the caller can close both on shutdown. Construction goes
    through :func:`build_canvas_runtime` — the package-owned seam that makes a
    runner without the canonical Run/NodeRun/Attempt binding unrepresentable.
    """
    import asyncpg

    from maistro.runs.wiring import wire_execution_spine

    pool = await asyncpg.create_pool(dsn=settings.pg_dsn)
    try:
        await assert_database_migrated(pool)
        # prime=False: the worker consumes admitted work; it does not create
        # authorization scope. The HTTP process that admits jobs owns the
        # Root Project priming.
        (
            _scope,
            run_store,
            _admitter,
            _templates,
            _schedules,
            _continuations,
        ) = await wire_execution_spine(
            None,
            pg_pool=pool,
            workspace_id=settings.workspace_id,
            prime=False,
        )
    except BaseException:
        await pool.close()
        raise

    engine = create_async_engine(sqlalchemy_asyncpg_url(settings.pg_dsn))
    store = PgCanvasStore(engine)
    # Every adapter the executor will call is checked here: a target that
    # resolves to a factory's ``None`` (or an object missing a method) must be
    # a startup config error, not a job that terminalizes a canonical Run as
    # failed after spending its retry budget.
    image_client = _require_adapter_methods(
        settings.image_client_target,
        await resolve_target(settings.image_client_target),
        "generate",
        "refine",
    )
    model_registry = _require_adapter_methods(
        settings.model_registry_target,
        await resolve_target(settings.model_registry_target),
        "is_registered",
        "get_default_draft",
    )
    warden = _require_adapter_methods(
        settings.warden_target,
        await resolve_target(settings.warden_target),
        "scan_prompt",
    )
    runtime = build_canvas_runtime(
        store=store,
        image_client=cast(Any, image_client),
        model_registry=cast(Any, model_registry),
        warden=cast(Any, warden),
        run_store=run_store,
        workspace_id=settings.workspace_id,
        project_id=settings.project_id,
        worker_id=settings.worker_id,
        lease_seconds=settings.lease_seconds,
        poll_interval=settings.poll_interval,
        reap_interval=settings.reap_interval,
        max_execution_seconds=settings.max_execution_seconds,
        concurrency=settings.concurrency,
    )
    return runtime, pool, engine


async def run_worker(
    settings: CanvasWorkerSettings,
    *,
    runtime_factory: Any = None,
    stop_event: asyncio.Event | None = None,
) -> int:
    """Run the worker until SIGTERM/SIGINT, then shut down boundedly.

    ``runtime_factory`` and ``stop_event`` are injection seams for tests and
    embedders; production uses the real composition and OS signals.
    """
    factory = runtime_factory if runtime_factory is not None else compose_runtime
    built = factory(settings)
    if isawaitable(built):
        built = await built
    runtime, pool, engine = cast("tuple[CanvasRuntime, Any, Any]", built)
    logger.info(
        "canvas_worker_ready worker=%s concurrency=%d",
        settings.worker_id,
        settings.concurrency,
    )
    stop = stop_event if stop_event is not None else asyncio.Event()
    install_signal_handlers(stop)
    runner_task: asyncio.Task[None] | None = None
    stop_waiter: asyncio.Task[bool] | None = None
    exit_code = 0
    try:
        runner_task = asyncio.create_task(runtime.runner.start(), name="canvas-worker-runner")
        stop_waiter = asyncio.create_task(stop.wait(), name="canvas-worker-stop")
        # Wake on whichever comes first: the stop signal — or the runner
        # dying. A service whose runner has crashed must exit and let the
        # supervisor restart it, not sit "running" while consuming nothing.
        await asyncio.wait({stop_waiter, runner_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        remove_signal_handlers()
        runtime.runner.stop()
        if runner_task is not None:
            _done, pending = await asyncio.wait({runner_task}, timeout=_SHUTDOWN_GRACE_SECONDS)
            if pending:
                logger.warning(
                    "canvas_worker_shutdown_timeout timeout=%ss; cancelling in-flight tick",
                    _SHUTDOWN_GRACE_SECONDS,
                )
                runner_task.cancel()
                _done2, pending2 = await asyncio.wait(
                    {runner_task}, timeout=_SHUTDOWN_GRACE_SECONDS
                )
                if pending2:
                    logger.error(
                        "canvas_worker_shutdown_abandoned; runner task ignored cancellation"
                    )
                    # Never await it again: a coroutine that suppressed
                    # CancelledError would hang shutdown forever. Attach a
                    # done callback so a late exception is still retrieved.
                    runner_task.add_done_callback(_consume_runner_outcome)
                elif runner_task.exception() is not None:
                    logger.error("canvas_worker_runner_failed", exc_info=runner_task.exception())
                    exit_code = 1
            elif runner_task.exception() is not None:
                logger.error("canvas_worker_runner_failed", exc_info=runner_task.exception())
                exit_code = 1
        if stop_waiter is not None and not stop_waiter.done():
            stop_waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stop_waiter
        await pool.close()
        await engine.dispose()
    logger.info("canvas_worker_stopped worker=%s", settings.worker_id)
    return exit_code


def _consume_runner_outcome(task: asyncio.Task[None]) -> None:
    """Retrieve an abandoned runner task's outcome, logging its error."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("canvas_worker_runner_failed", exc_info=exc)


def install_signal_handlers(stop: asyncio.Event) -> None:
    """Ask for a graceful stop on SIGTERM/SIGINT where the loop supports it."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)


def remove_signal_handlers() -> None:
    """Undo :func:`install_signal_handlers` (symmetric, best-effort)."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.remove_signal_handler(sig)


def main() -> int:
    """Console-script entry point (``maistro-canvas-worker``)."""
    logging.basicConfig(
        level=os.getenv("MAISTRO_CANVAS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = CanvasWorkerSettings.from_env()
    except WorkerConfigError as exc:
        logger.error("canvas_worker_config_error error=%s", exc)
        return 2
    try:
        return asyncio.run(run_worker(settings))
    except WorkerConfigError as exc:
        logger.error("canvas_worker_config_error error=%s", exc)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - signal path on proactor loops
        return 0
    except Exception:
        logger.exception("canvas_worker_crashed")
        return 1


def load_env_file(path: str | PathLike[str]) -> dict[str, str]:
    """Read a KEY=VALUE file into a dict (for ``--env-file`` style launches).

    Compose/systemd supply environment themselves; this exists so an operator
    can preview resolved settings and tests can drive ``from_env`` without
    touching process env. Lines are ``KEY=VALUE``; ``#`` starts a comment;
    no value interpolation is performed.
    """
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if not separator:
                raise WorkerConfigError(f"env file line {raw_line.rstrip()!r} is not KEY=VALUE")
            values[key.strip()] = value.strip()
    return values


__all__ = [
    "CanvasWorkerSettings",
    "WorkerConfigError",
    "assert_database_migrated",
    "compose_runtime",
    "load_env_file",
    "main",
    "resolve_target",
    "run_worker",
    "sqlalchemy_asyncpg_url",
]
