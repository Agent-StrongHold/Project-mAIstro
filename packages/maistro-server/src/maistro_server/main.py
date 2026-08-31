"""Maistro Engine — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import signal
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import maistro.agents.conductor as conductor
import maistro.config.settings as settings_module
import maistro.memory.store as memory_store
import maistro.persistence as persistence
from maistro.agents.catalog import AgentCatalog
from maistro.agents.pm_fleet import register_pm_fleet
from maistro.config.database import resolve_database_url, to_asyncpg_dsn
from maistro.config.settings import Settings, get_settings
from maistro.container import POSTGRES_SCHEMES, create_container
from maistro.graph.concurrency import configure_graph_concurrency
from maistro.http import aclose_shared_clients, configure_shared_http
from maistro.observability.logging import configure_logging
from maistro.observability.middleware import RequestIDMiddleware
from maistro.security.outbound import configure_outbound_policy, configured_endpoints
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.progress_webhook import ProgressWebhookNotifier
from maistro.tasks.queue import configure_task_queue, reset_task_queue
from maistro.tasks.runner import TaskRunner
from maistro.tools.sandbox.server import cleanup_all_containers
from maistro.types.config import AgentConfig
from maistro_server.api import (
    canvas,
    chat_completions,
    health,
    metrics,
    models,
    runs,
    tasks,
    webhooks,
    workspaces,
    ws,
)
from maistro_server.api.chat_completions import RUN_ID_HEADER
from maistro_server.api.middleware import PayloadSizeLimitMiddleware, SecurityHeadersMiddleware
from maistro_server.api.rate_limit import RateLimitMiddleware
from maistro_server.api.schemas import ErrorDetail, ErrorResponse
from maistro_server.conductor_agent import CONDUCTOR_AGENT_NAME, ConductorAgent
from maistro_server.startup import StartupPhase, get_startup_phase, set_startup_phase

if TYPE_CHECKING:
    from maistro.agents.base import Agent

logger = structlog.get_logger()

_runner: TaskRunner | None = None

# Single source of truth for version — read from installed package metadata
try:
    APP_VERSION = importlib.metadata.version("maistro-server")
except importlib.metadata.PackageNotFoundError:
    APP_VERSION = "0.9.0-dev"

# Graceful shutdown drain timeout (seconds)
SHUTDOWN_DRAIN_TIMEOUT = 30.0


def _validate_startup(settings: Settings) -> None:
    """Fail-fast startup checks. Raises RuntimeError if critical config is missing."""
    if settings.require_auth and not settings.api_keys:
        raise RuntimeError(
            "CRITICAL: No API keys configured and REQUIRE_AUTH is true. "
            "Set API_KEYS env var or set REQUIRE_AUTH=false for local development."
        )
    if settings.require_webhook_secrets and not (
        settings.github_webhook_secret and settings.ci_webhook_secret
    ):
        raise RuntimeError(
            "CRITICAL: REQUIRE_WEBHOOK_SECRETS is true but GITHUB_WEBHOOK_SECRET "
            "and/or CI_WEBHOOK_SECRET is unset. Set both, or set "
            "REQUIRE_WEBHOOK_SECRETS=false if this deployment receives no webhooks."
        )
    if not _router_api_key().strip():
        # Stated here rather than left to surface from inside container wiring
        # (#142). This app now builds a `Container`, and `create_container`
        # refuses an empty `router_api_key` — correctly, but with a `ConfigError`
        # raised several frames deep in lifespan, which reads as a bug rather
        # than as a missing setting. Said once, by name, beside the other two.
        raise RuntimeError(
            "CRITICAL: ROUTER_API_KEY is unset. The server builds a maistro-core "
            "Container so that every chat turn reaches the Conduit, and that "
            "requires it. Set ROUTER_API_KEY."
        )


async def _run_store_pool() -> Any:
    """An asyncpg pool for the canonical spine, or None (#132).

    None is an ordinary answer, not a degraded one: a deployment with no
    PostgreSQL database gets the in-process store and is told so. Only a
    *configured but unreachable* server is a startup failure, and that failure
    belongs to `get_pool` rather than to a guess made here.

    The URL comes from the one resolver alembic also uses (#187), so the spine
    lands in the database the migrations describe rather than in whichever one a
    second reading of the environment happened to name.
    """
    database_url = resolve_database_url()
    if not database_url.startswith(POSTGRES_SCHEMES):
        return None

    return await persistence.get_pool(to_asyncpg_dsn(database_url))


def _router_api_key() -> str:
    """`ROUTER_API_KEY`, from the same place the rest of the config reads it.

    Not on `Settings`. `Settings` is the server's own env-driven model;
    `router_api_key` lives on `MaistroYamlConfig`, which `config.loader` fills
    from `maistro.yaml` and the environment. Read through that when it has been
    loaded, and fall back to the variable itself when it has not — a server
    started without a YAML file still has the environment.
    """
    yaml_config = settings_module.get_yaml_config()
    if yaml_config is not None and yaml_config.router_api_key:
        return yaml_config.router_api_key
    return os.getenv("ROUTER_API_KEY", "")


def _agents_dir() -> str:
    """`agents_dir`, from the same place, for the same reason."""
    yaml_config = settings_module.get_yaml_config()
    return yaml_config.agents_dir if yaml_config is not None else ""


def _agent_config(settings: Settings) -> AgentConfig:
    """The `AgentConfig` this server's Container is wired from (#142).

    Mapped explicitly rather than by passing `Settings` through. They are
    different models — `AgentConfig` is what `create_container` receives, and
    several of these fields are not on `Settings` at all — so a structural
    overlap between them is how a setting comes to exist in one place and
    quietly do nothing in the other.

    `database_url` comes from the resolver alembic also uses (#187), which is
    the same one `_run_store_pool` reads, so the container cannot decide it is
    talking to a different database than the pool it is handed.

    `workspace_id` is stated for the reason `hive-conductor` states it: core
    defaults it to `"default"` too, so the value is identical today — but a
    server that changed its default Workspace and a core that did not would
    then disagree about where unscoped Runs live, with nothing saying so.
    """
    return AgentConfig(
        router_api_key=_router_api_key(),
        litellm_url=settings.litellm.base_url,
        litellm_key=settings.litellm.master_key,
        agents_dir=_agents_dir(),
        database_url=resolve_database_url(),
        workspace_id=settings.workspace_id,
    )


async def _build_container(settings: Settings, pg_pool: Any) -> Any:
    """The process's one Container, with a roster it can actually route to.

    `Conduit.route_request` answers "No agents available." when `agents` is
    empty, and this server has never built any. `run_task` needs no roster,
    which is why the OpenAI door works today on deployments that configured
    none — so an empty map here would convert every one of their chat turns
    into a refusal.

    `ConductorAgent` is that floor: the same executor, reached through the
    pipeline instead of around it.

    **`agents_dir` is deliberately not read here.** It is on `AgentConfig` and
    `create_agents` would consume it, but that factory needs an LLM client and
    a `Container` does not carry one — `hive-conductor` builds its own before
    calling it. Choosing this server's client is a deployment decision nobody
    has asked for yet: `agents_dir` defaults to empty and this app has never
    read it, so wiring a roster now would be inventing the requirement rather
    than meeting it. The setting is carried on the config so that whoever does
    want one starts from a Container that already has it.
    """
    container = await create_container(_agent_config(settings), pg_pool=pg_pool)
    # `Container.agents` is typed `dict[str, Agent]`, and `Agent` is a concrete
    # base class rather than a protocol — but `Conduit` uses the map
    # structurally: `handle(...)`, and `priority_tier` only if present.
    # `ConductorAgent` provides exactly that and deliberately does not subclass
    # `BaseAgent`, which would bring a second strategy stack and a second
    # extraction pass over an answer `run_task` has already produced.
    container.agents = cast("dict[str, Agent]", {CONDUCTOR_AGENT_NAME: ConductorAgent()})
    await logger.ainfo("container_wired", agents=sorted(container.agents))
    return container


@asynccontextmanager
async def _runtime_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start/stop the background task runner with the app lifecycle."""
    global _runner

    # Configure structured logging (JSON in production, console in debug)
    settings = get_settings()
    configure_logging(debug=settings.debug, json_output=not settings.debug)

    # Fail-fast startup validation
    _validate_startup(settings)

    # Explicitly instantiate the graph LLM admission gate during application
    # startup. Lazy construction remains a safe library fallback, but the server
    # should own its runtime resource initialization rather than relying on the
    # first graph node to do it implicitly.
    configure_graph_concurrency()

    # Size the shared outbound HTTP pool before the first request — clients
    # already built keep the limits they were created with.
    configure_shared_http(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_keepalive_connections,
        keepalive_expiry=settings.http_keepalive_expiry_s,
    )

    # And name the endpoints this deployment is supposed to reach, before the
    # first request (#155). The guard at that pool's transport is on for
    # everything else; an endpoint nobody configured is not reachable by
    # accident.
    configure_outbound_policy(*configured_endpoints(settings))

    # Initialise database engine (no-op if DATABASE_URL unset)
    memory_store.get_engine()

    # Canonical execution identity (#41): every task submitted through /tasks
    # gets a Run over a one-node Graph, and the response carries its run_id.
    #
    # Durable when this deployment names a PostgreSQL database (#132). The spine
    # is the one thing that must not be ephemeral — it is what an audit, a
    # recovery, a retry and a resumed HITL pause all read — so an in-process
    # store is the fallback, not the default, and the log says which one is live
    # rather than leaving a run_id that silently stops resolving to be
    # discovered.
    spine_pool = await _run_store_pool()
    # One Container, and the spine comes *from* it (ADR-082426-2192, #142).
    # `create_container` wires `wire_execution_spine` and `wire_chat_admission`
    # itself, so calling either here as well would give this process two
    # RunStores — a run_id returned by /tasks would not resolve for a chat turn
    # and vice versa, which is an advertised handle that silently stops
    # resolving. The pool opened above is handed over rather than left for the
    # container to open a second one against the same server.
    container = await _build_container(settings, spine_pool)
    app.state.container = container
    run_store = container.run_store
    if spine_pool is None:
        await logger.awarning(
            "run_store_in_process_only",
            workspace_id=settings.workspace_id,
            detail=(
                "no PostgreSQL database is configured, so Runs admitted by /tasks "
                "are lost on restart"
            ),
        )
    queue = configure_task_queue(admitter=container.task_admitter)
    # The handles these APIs return must resolve against the exact stores the
    # Container selected, not lookalike stores reconstructed by the server.
    runs.configure_run_store(run_store)
    workspaces.configure_workspace_store(container.workspace_store)
    # The OpenAI-compatible door now routes through the same Container (#142),
    # which owns the Gate scan, the Run admission and the terminalization that
    # #150 had to build here for want of one.
    chat_completions.configure_container(container)

    progress_wh: ProgressWebhookNotifier | None = None
    if settings.task_progress_webhook_url.strip():
        progress_wh = ProgressWebhookNotifier(
            post_url=settings.task_progress_webhook_url.strip(),
            api_key=settings.task_progress_webhook_api_key,
        )

    _runner = TaskRunner(
        queue,
        executor=conductor.run_task,
        progress_webhook=progress_wh,
        # Same store the admitter files Runs in, so a task's NodeRun and
        # Attempt land under the Run `POST /tasks` already returned (#143).
        attempts=TaskAttemptExecutor(run_store),
    )
    await _runner.start()
    await logger.ainfo("maistro_engine_started", version=APP_VERSION)

    # Register graceful shutdown handler
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(_graceful_shutdown(s)),  # type: ignore[misc]
        )

    try:
        yield
    finally:
        # Graceful shutdown: drain tasks → cleanup containers → flush observability
        if _runner:
            await _runner.stop(drain_timeout=SHUTDOWN_DRAIN_TIMEOUT)

        # Drop the queue singleton after draining, so a later lifespan in the same
        # interpreter can install a fresh one. Startup refuses to replace a queue
        # that has accepted tasks — correctly, since a queued task cannot be given a
        # Run afterwards — and without this that guard latched permanently.
        reset_task_queue()
        runs.configure_run_store(None)
        workspaces.configure_workspace_store(None)

        await cleanup_all_containers()

        # Release pooled outbound connections. After the runner has drained, so
        # in-flight tasks still have their client.
        await aclose_shared_clients()

        # Dispose database engine
        engine = memory_store.get_engine()
        if engine:
            await engine.dispose()
        memory_store.reset_engine_cache()

        await logger.ainfo("maistro_engine_stopped")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Expose deterministic startup state around the real runtime lifespan."""
    set_startup_phase(app, StartupPhase.STARTING)
    try:
        async with _runtime_lifespan(app):
            set_startup_phase(app, StartupPhase.COMPLETE)
            try:
                yield
            finally:
                set_startup_phase(app, StartupPhase.NOT_STARTED)
    except BaseException:
        if get_startup_phase(app) is StartupPhase.STARTING:
            set_startup_phase(app, StartupPhase.FAILED)
        raise


async def _graceful_shutdown(sig: signal.Signals) -> None:
    """Handle shutdown signals with task draining."""
    await logger.ainfo("shutdown_signal_received", signal=sig.name)
    if _runner:
        await _runner.drain(timeout=30)


app = FastAPI(
    title="Maistro Engine",
    description="Software engineering department in a box",
    version=APP_VERSION,
    lifespan=lifespan,
)
set_startup_phase(app, StartupPhase.NOT_STARTED)

# --- Middleware (applied in reverse order — last added = first executed) ---

_settings = get_settings()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    # Response headers a browser client may actually read. Without this the
    # header is sent and then hidden: `response.headers` in browser JS only
    # exposes the CORS-safelisted set, so `X-Maistro-Run-Id` would have been
    # an advertised correlation path that no cross-origin UI could follow.
    expose_headers=[RUN_ID_HEADER, "X-Request-ID"],
)

# Rate limiting
app.add_middleware(RateLimitMiddleware)

# Request correlation IDs
app.add_middleware(RequestIDMiddleware)

# Global payload size limit — rejects oversized/malformed bodies before
# CORS/rate-limit/request-id do any work.
app.add_middleware(
    PayloadSizeLimitMiddleware,
    max_bytes=_settings.max_request_body_bytes,
)

# Security headers — the true outermost middleware (added last), so headers
# land on every response, including early rejections from the middlewares
# added above (e.g. 413 from PayloadSizeLimitMiddleware, 429 from RateLimit).
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Wrap HTTPException in consistent error envelope."""
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                type="http_error",
                message=exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                request_id=request_id,
            ),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions — log and return structured JSON."""
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
    logger.exception(
        "unhandled_exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(
                type="internal_error",
                message="Internal server error",
                request_id=request_id,
            ),
        ).model_dump(),
    )


# Register routers — unversioned operational endpoints
app.include_router(health.router)
app.include_router(metrics.router)

# API v1 — all business endpoints under /v1 prefix for versioning
API_V1_PREFIX = "/v1"
app.include_router(tasks.router, prefix=API_V1_PREFIX)
app.include_router(runs.router, prefix=API_V1_PREFIX)
app.include_router(workspaces.router, prefix=API_V1_PREFIX)
app.include_router(chat_completions.router, prefix=API_V1_PREFIX)
app.include_router(models.router, prefix=API_V1_PREFIX)
app.include_router(webhooks.router, prefix=API_V1_PREFIX)
app.include_router(ws.router, prefix=API_V1_PREFIX)

# API v2 — canvas ability boundary (ADR-045 / SPEC-070226-8239 Phase 1).
# The router carries its own /v2/canvas prefix (ADR-042 mount). Deployments
# must inject app.state.canvas_store (and optionally canvas_compositor,
# canvas_events, canvas_asset_registry) — see maistro_server.api.canvas.
app.include_router(canvas.router)

# Backward compatibility — also mount at root (will be removed in v2)
app.include_router(tasks.router)
app.include_router(runs.router)
app.include_router(workspaces.router)
app.include_router(chat_completions.router)
app.include_router(models.router)
app.include_router(webhooks.router)
app.include_router(ws.router)

# Legacy Knights dashboard removed — Hive Conductor (port 8101) is the product UI.