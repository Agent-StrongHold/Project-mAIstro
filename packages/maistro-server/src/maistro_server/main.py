"""Maistro Engine — FastAPI application entry point."""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import signal
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from maistro.config.settings import Settings, get_settings
from maistro.graph.concurrency import configure_graph_concurrency
from maistro.http import aclose_shared_clients, configure_shared_http
from maistro.observability.logging import configure_logging
from maistro.observability.middleware import RequestIDMiddleware
from maistro.tasks.progress_webhook import ProgressWebhookNotifier
from maistro.tasks.queue import get_task_queue
from maistro.tasks.runner import TaskRunner
from maistro.tools.sandbox.server import cleanup_all_containers
from maistro_server.api import (
    agents,
    canvas,
    chat_completions,
    health,
    metrics,
    models,
    tasks,
    webhooks,
    ws,
)
from maistro_server.api.middleware import PayloadSizeLimitMiddleware, SecurityHeadersMiddleware
from maistro_server.api.rate_limit import RateLimitMiddleware
from maistro_server.api.schemas import ErrorDetail, ErrorResponse

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    # Wire executor via import — the runner no longer imports conductor directly
    from maistro.agents.conductor import run_task

    # Initialise database engine (no-op if DATABASE_URL unset)
    from maistro.memory.store import get_engine

    get_engine()

    queue = get_task_queue()

    if os.getenv("MAISTRO_POC_MODE", "").strip().lower() == "pm":
        from maistro.agents.catalog import AgentCatalog
        from maistro.agents.pm_fleet import register_pm_fleet

        catalog = AgentCatalog()
        register_pm_fleet(catalog)
        app.state.pm_catalog = catalog
        await logger.ainfo("pm_fleet_catalog_seeded", agents=len(catalog.list_agents()))

    progress_wh: ProgressWebhookNotifier | None = None
    if settings.task_progress_webhook_url.strip():
        progress_wh = ProgressWebhookNotifier(
            post_url=settings.task_progress_webhook_url.strip(),
            api_key=settings.task_progress_webhook_api_key,
        )

    _runner = TaskRunner(queue, executor=run_task, progress_webhook=progress_wh)
    await _runner.start()
    await logger.ainfo("maistro_engine_started", version=APP_VERSION)

    # Register graceful shutdown handler
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_graceful_shutdown(s)))  # type: ignore[misc]

    yield

    # Graceful shutdown: drain tasks → cleanup containers → flush observability
    if _runner:
        await _runner.stop(drain_timeout=SHUTDOWN_DRAIN_TIMEOUT)

    await cleanup_all_containers()

    # Release pooled outbound connections. After the runner has drained, so
    # in-flight tasks still have their client.
    await aclose_shared_clients()

    # Dispose database engine
    from maistro.memory.store import get_engine, reset_engine_cache

    engine = get_engine()
    if engine:
        await engine.dispose()
    reset_engine_cache()

    await logger.ainfo("maistro_engine_stopped")


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

# --- Middleware (applied in reverse order — last added = first executed) ---

_settings = get_settings()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
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
app.include_router(agents.router, prefix=f"{API_V1_PREFIX}/maistro")
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
app.include_router(chat_completions.router)
app.include_router(models.router)
app.include_router(webhooks.router)
app.include_router(ws.router)

# Legacy Knights dashboard removed — Hive Conductor (port 8101) is the product UI.
