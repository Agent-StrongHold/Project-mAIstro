"""Maistro Engine — FastAPI application entry point."""

from __future__ import annotations

import importlib.metadata
import os
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
from maistro.agents.types import ConductorOutput
from maistro.config.database import resolve_database_url, to_asyncpg_dsn
from maistro.config.settings import Settings, get_settings
from maistro.container import POSTGRES_SCHEMES, create_container
from maistro.graph.concurrency import configure_graph_concurrency
from maistro.http import aclose_shared_clients, configure_shared_http
from maistro.observability.logging import configure_logging
from maistro.observability.middleware import RequestIDMiddleware
from maistro.security.outbound import configure_outbound_policy, configured_endpoints
from maistro.tasks.execution import TaskAttemptExecutor
from maistro.tasks.models import TaskCreate
from maistro.tasks.progress_webhook import ProgressWebhookNotifier
from maistro.tasks.queue import configure_task_queue, get_task_queue, reset_task_queue
from maistro.tasks.runner import TaskRunner
from maistro.types.config import AgentConfig, ModelBindingConfig, SecurityConfig
from maistro_server.api import (
    a2a,
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
from maistro_server.api.auth import API_KEY_ENTRY_DOC, invalid_api_key_entries
from maistro_server.api.chat_completions import RUN_ID_HEADER
from maistro_server.api.middleware import PayloadSizeLimitMiddleware, SecurityHeadersMiddleware
from maistro_server.api.rate_limit import RateLimitMiddleware
from maistro_server.api.schemas import ErrorDetail, ErrorResponse
from maistro_server.conductor_agent import CONDUCTOR_AGENT_NAME, ConductorAgent
from maistro_server.startup import StartupPhase, get_startup_phase, set_startup_phase

if TYPE_CHECKING:
    from maistro.agents.base import Agent
    from maistro.capabilities.model_chat import ModelChatEgress

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
    # #843: fail closed at boot rather than serving a config where keys
    # silently share an invented identity. Descriptions never echo key
    # material (invalid_api_key_entries guarantees that).
    invalid_entries = invalid_api_key_entries(settings)
    if invalid_entries:
        raise RuntimeError(
            "CRITICAL: API_KEYS entries without an explicit canonical "
            f"principal (#843): {'; '.join(invalid_entries)}. Rewrite every "
            f"entry as {API_KEY_ENTRY_DOC}. A legacy plain key keeps working "
            "once prefixed with its principal — the same secret keeps "
            "authenticating, now attributed to the named principal. See "
            "docs/install/api-key-identity.md for the migration path."
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
        # The Sentinel permission table is fail-closed (#1165): an empty table
        # denies every tool, so the grants an operator states in
        # `security.permission_preset` / `security.permissions` must reach the
        # config the Container is built from, or no deployment can ever
        # authorize one.
        security=_security_config(),
        # Same reasoning, for the canonical `model.chat` Binding authority
        # (#1079): `bootstrap_model_bindings()` reads `AgentConfig.model_bindings`
        # and authorizes nothing when it is empty, so an operator's
        # `model_bindings:` YAML declarations must reach this config or every
        # `llm.summarize` node refuses every Binding in production.
        model_bindings=_model_bindings(),
    )


def _security_config() -> SecurityConfig:
    """The Sentinel grants, from `maistro.yaml`'s `security` section.

    Read through the loaded YAML config like `_router_api_key` and
    `_agents_dir`, because that is where an operator states them; a server
    started without a YAML file gets the shipped defaults, which is the empty
    fail-closed table (#1165).
    """
    yaml_config = settings_module.get_yaml_config()
    if yaml_config is None:
        return SecurityConfig()
    return SecurityConfig(
        permission_preset=yaml_config.security.permission_preset,
        permissions=yaml_config.security.permissions,
    )


def _model_bindings() -> list[ModelBindingConfig]:
    """The operator-declared `model.chat` Bindings, from `maistro.yaml`'s
    `model_bindings` section.

    Read through the loaded YAML config like `_security_config`, because that
    is where an operator states them; a server started without a YAML file
    gets the shipped default, which is the empty fail-closed list -- no
    Binding, no authorization (#1079).
    """
    yaml_config = settings_module.get_yaml_config()
    if yaml_config is None:
        return []
    return list(yaml_config.model_bindings)


async def _build_container(settings: Settings, pg_pool: Any) -> tuple[Any, ModelChatEgress]:
    """The process's one Container and the governed egress it comes with.

    `Conduit.route_request` answers "No agents available." when `agents` is
    empty, and this server has never built any. `run_task` needs no roster,
    which is why the OpenAI door works today on deployments that configured
    none — so an empty map here would convert every one of their chat turns
    into a refusal.

    `ConductorAgent` is that floor: the same executor, reached through the
    pipeline instead of around it.

    The egress is returned rather than rebuilt per caller because both doors
    into the conductor LLM path need the same authority (#718): the chat door
    through `ConductorAgent`, and the `/tasks` worker through its executor.
    Two constructions over one Container would still share its effect
    context, but one construction keeps the deployment's gateway endpoint —
    and the fail-closed Binding scope its credential registers in — a single
    decision this composition point owns.

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
    from maistro.capabilities.model_chat import ModelChatEgress
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint

    governed_egress = ModelChatEgress(
        container.capability_effects,
        registry=container.provider_registry,
        router=container.llm_router,
        endpoint=GatewayEndpoint(
            base_url=settings.litellm.base_url,
            api_key=settings.litellm.master_key,
        ),
    )
    # `Container.agents` is typed `dict[str, Agent]`, and `Agent` is a concrete
    # base class rather than a protocol — but `Conduit` uses the map
    # structurally: `handle(...)`, and `priority_tier` only if present.
    # `ConductorAgent` provides exactly that and deliberately does not subclass
    # `BaseAgent`, which would bring a second strategy stack and a second
    # extraction pass over an answer `run_task` has already produced.
    container.agents = cast(
        "dict[str, Agent]",
        {
            CONDUCTOR_AGENT_NAME: ConductorAgent(
                governed_egress=governed_egress,
                workspace_id=settings.workspace_id,
                router=container.llm_router,
            )
        },
    )
    await logger.ainfo("container_wired", agents=sorted(container.agents))
    return container, governed_egress


async def _drain_queue_singleton() -> None:
    """Drain the task queue's in-flight receipt writes before teardown (#849).

    The runner drains its own workers' writes in `stop()`; this covers a
    straggler request that terminalized a task after the runner stopped, whose
    scheduled write would otherwise be abandoned when the singleton is dropped.
    Idempotent after the runner's drain — a queue with nothing scheduled returns
    immediately — and best-effort, because shutdown must proceed even if the
    drain itself fails (the canonical Run still holds the truth, and recovery
    reconciles from it).
    """
    try:
        await get_task_queue().drain_persistence()
    except Exception:
        await logger.awarning("task_receipt_drain_on_shutdown_failed", exc_info=True)


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
    container, governed_egress = await _build_container(settings, spine_pool)
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
    queue = configure_task_queue(
        admitter=container.task_admitter,
        # Same claim tier the spine selected (#1176): a retry reconciles across
        # a restart or a replica handoff exactly as far as the Runs it names
        # are durable.
        idempotency_store=container.task_idempotency,
    )
    # Rebuild receipts from canonical QUEUED task Runs before starting workers.
    # This is the restart-safe handoff for both admission/receipt gaps; the Run
    # already contains the immutable payload needed to execute the original id —
    # including the originating-principal evidence (#1057), which survives the
    # restart in the same committed payload the admission wrote.
    await queue.recover(run_store)
    # The handles these APIs return must resolve against the exact stores the
    # Container selected, not lookalike stores reconstructed by the server.
    runs.configure_run_store(run_store)
    a2a.configure_a2a_admission(
        run_store,
        container.project_scope_store,
        workspace_id=settings.workspace_id,
    )
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

    async def runner_executor(task: TaskCreate) -> ConductorOutput:
        # #718: the `/tasks` worker is the server's second door into the
        # conductor LLM path, and it crosses the same canonical effect
        # authority the chat door's `ConductorAgent` does — the egress built
        # with this Container, not a per-caller recording callback. Without
        # it, every task this queue completes leaves no Invocation and no
        # quota evidence, while per-provider rows present as complete.
        return await conductor.run_task(
            task,
            governed_egress=governed_egress,
            workspace_id=settings.workspace_id,
            project_id="agent-runtime",
        )

    _runner = TaskRunner(
        queue,
        executor=runner_executor,
        progress_webhook=progress_wh,
        # Same store the admitter files Runs in, so a task's NodeRun and
        # Attempt land under the Run `POST /tasks` already returned (#143).
        attempts=TaskAttemptExecutor(run_store),
    )
    await _runner.start()
    await logger.ainfo("maistro_engine_started", version=APP_VERSION)

    # No signal handler is installed here. Uvicorn owns SIGTERM/SIGINT for the
    # process: its `handle_exit` sets `should_exit`, the main loop returns, and
    # the lifespan shutdown block below runs as part of `server.shutdown()`.
    # This used to install its own `loop.add_signal_handler` that drained the
    # runner directly — which *replaced* Uvicorn's handler (asyncio allows one
    # handler per signal), so `should_exit` was never set: the server ignored
    # SIGTERM, none of the shutdown block ran, and the container's grace
    # deadline ended in SIGKILL with sandboxes, pooled clients and the DB
    # engine all still live (#819). Draining composes through lifespan
    # shutdown instead; see the `finally` block and `SHUTDOWN_DRAIN_TIMEOUT`.

    try:
        yield
    finally:
        # Graceful shutdown: drain tasks → flush quota snapshots → cleanup.
        # Reached via Uvicorn's SIGTERM/SIGINT handling — the drain is bounded
        # (`SHUTDOWN_DRAIN_TIMEOUT`), tasks the deadline cancels are marked
        # FAILED, and shutdown continues to process exit either way.
        if _runner:
            await _runner.stop(drain_timeout=SHUTDOWN_DRAIN_TIMEOUT)
        container = getattr(app.state, "container", None)
        if container is not None:
            try:
                await container.flush_usage_log()
            except Exception:
                await logger.aerror("usage_log_flush_failed", exc_info=True)
            await container.aclose()

        # Drop the queue singleton after draining, so a later lifespan in the same
        # interpreter can install a fresh one. Startup refuses to replace a queue
        # that has accepted tasks — correctly, since a queued task cannot be given a
        # Run afterwards — and without this that guard latched permanently.
        await _drain_queue_singleton()
        reset_task_queue()
        runs.configure_run_store(None)
        a2a.configure_a2a_admission(None, None)
        workspaces.configure_workspace_store(None)

        # Imported here, not at module scope: the sandbox MCP server is the
        # one import in this module's graph that pulls the optional fastmcp
        # stack (maistro-core's `[llm]` extra). Importing it eagerly made
        # merely *importing* this app require that extra — so any leaner
        # environment (a test interpreter, an embedding host) failed at
        # import time even though it never starts a sandbox. If the extra is
        # absent no sandbox containers can exist, so there is nothing to
        # clean up and skipping the call is correct, not a fallback (#1057).
        try:
            from maistro.tools.sandbox.server import cleanup_all_containers
        except ImportError:
            pass
        else:
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
    # `Retry-After` likewise: a refused chat turn's 503 (#1108) names its
    # retry delay there, and it is not on the safelist either.
    expose_headers=[RUN_ID_HEADER, "X-Request-ID", "Retry-After"],
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
        # Kept, not rebuilt: a 429's or 503's Retry-After or a 401's
        # WWW-Authenticate is part of the status the route chose.
        headers=exc.headers,
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
app.include_router(a2a.router)

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
