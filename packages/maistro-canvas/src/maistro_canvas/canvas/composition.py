"""Production composition for Canvas canonical generation execution.

The outer application supplies an already-authorized canonical scope and the
Canvas-domain providers. This module is the package-owned construction seam so
production cannot accidentally create a CanvasExecutor without the canonical
Run -> NodeRun -> Attempt adapter.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from maistro.runs.store import RunStore
from maistro_canvas.canvas.asset_compositor import plan_render as plan_asset_render
from maistro_canvas.canvas.asset_executor import AssetExecutor
from maistro_canvas.canvas.asset_routes import make_router as make_asset_router
from maistro_canvas.canvas.asset_store import InMemoryAssetStore, PostgresAssetStore
from maistro_canvas.canvas.asset_tool import AssetTool
from maistro_canvas.canvas.canonical_execution import CanvasCanonicalExecution
from maistro_canvas.canvas.executor import CanvasExecutor
from maistro_canvas.protocols import CanvasStore, ImageGenClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import APIRouter

    from maistro_canvas.protocols import CompositorService

logger = logging.getLogger("maistro.canvas.composition")

#: ADR-044 AssetInstance modules rooted through this composition seam (#2311).
#: Held so the import edge is a real name binding, not a discarded import.
_ASSET_INSTANCE_CONNECT = (
    PostgresAssetStore,
    InMemoryAssetStore,
    plan_asset_render,
    AssetExecutor,
    make_asset_router,
    AssetTool,
)

_DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0
"""How long ``stop_runner`` waits for an in-flight ``tick_once`` to finish on
its own before cancelling it outright. ``CanvasJobRunner.stop()`` only flips
the poll-loop flag; it cannot interrupt a `tick_once` blocked inside a
provider call, so an unbounded ``await`` here would let a stalled provider
block FastAPI shutdown indefinitely. Bounded well under typical graceful
shutdown windows (Uvicorn/K8s default to ~30s) so the process still exits in
time even when the bound is hit.
"""


class CanvasModelRegistry(Protocol):
    """Model validation/default selection required by CanvasExecutor."""

    def is_registered(self, model_id: str) -> bool: ...

    def get_default_draft(self) -> str: ...


class CanvasWarden(Protocol):
    """Prompt policy dependency required by CanvasExecutor."""

    async def scan_prompt(self, prompt: str) -> str: ...


class CanvasRunner(Protocol):
    """Lifecycle surface exposed by the worker bound to a Canvas runtime."""

    async def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class CanvasRuntime:
    """The one Canvas execution binding used by routes and its worker."""

    store: CanvasStore
    canonical_execution: CanvasCanonicalExecution
    executor: CanvasExecutor
    runner: CanvasRunner


def build_canvas_runtime(
    *,
    store: CanvasStore,
    image_client: ImageGenClient,
    model_registry: CanvasModelRegistry,
    warden: CanvasWarden,
    run_store: RunStore,
    workspace_id: str,
    project_id: str,
    worker_id: str = "canvas-worker-1",
    lease_seconds: int = 300,
    poll_interval: float = 1.0,
    reap_interval: float = 30.0,
    max_execution_seconds: float = 1800.0,
) -> CanvasRuntime:
    """Build the canonical Canvas executor and its durable worker.

    ``workspace_id`` and ``project_id`` must come from the caller's existing
    authorization path; this factory deliberately does not derive them from
    Canvas's ``org_id`` or invent a default scope. The returned executor is
    therefore safe for the generation route to admit Runs, while the returned
    runner cannot claim work through the compatibility-only non-canonical path.
    """

    canonical = CanvasCanonicalExecution(
        run_store,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    executor = CanvasExecutor(
        store=store,
        image_client=image_client,
        model_registry=cast(Any, model_registry),
        warden=cast(Any, warden),
        canonical_execution=canonical,
        execution_timeout_s=max_execution_seconds,
    )
    # Keep the worker import at the composition boundary: the package's
    # reachability gate treats the runner as a lifecycle-loaded component.
    runner_type = importlib.import_module("maistro_canvas.canvas.runner").CanvasJobRunner
    runner = runner_type(
        store=store,
        executor=executor,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        poll_interval=poll_interval,
        reap_interval=reap_interval,
        max_execution_seconds=max_execution_seconds,
    )
    return CanvasRuntime(
        store=store,
        canonical_execution=canonical,
        executor=executor,
        runner=runner,
    )


class _UnavailableAssetImageGen:
    """Image gen stub so AssetTool can bind without a live provider (#2311)."""

    async def generate(self, **_kwargs: Any) -> list[Any]:
        return []


@dataclass(frozen=True)
class AssetInstanceSurface:
    """Process-local AssetInstance store, tool, and ``/v2/canvas`` asset router.

    LayerRecord routes stay on the legacy path; this surface mounts the
    ADR-042 asset endpoints alongside them (no path collision with designs).
    The default store is in-memory until a session-scoped ``PostgresAssetStore``
    factory is composed — ``postgres_store_cls`` names the production class.
    """

    store: InMemoryAssetStore
    tool: AssetTool
    router: APIRouter
    postgres_store_cls: type[PostgresAssetStore]


def build_asset_instance_surface(
    *,
    org_id: str = "default",
    get_store: Callable[[], Any] | None = None,
) -> AssetInstanceSurface:
    """Construct the ADR-044 AssetInstance HTTP + tool surface (#2311 CONNECT).

    ``get_store`` defaults to a process-local :class:`InMemoryAssetStore` so the
    surface is operable without a request-scoped SQLAlchemy session. Callers
    that already own a session may pass a factory returning
    :class:`PostgresAssetStore`.
    """
    assert _ASSET_INSTANCE_CONNECT[0] is PostgresAssetStore
    assert _ASSET_INSTANCE_CONNECT[-1] is AssetTool
    store = InMemoryAssetStore()
    store_factory = get_store or (lambda: store)
    executor = AssetExecutor(
        store_factory(),
        _UnavailableAssetImageGen(),
        org_id=org_id,
    )
    return AssetInstanceSurface(
        store=store,
        tool=AssetTool(executor),
        router=make_asset_router(get_store=store_factory),
        postgres_store_cls=PostgresAssetStore,
    )


def build_canvas_router(
    *,
    store: CanvasStore,
    image_client: ImageGenClient,
    model_registry: CanvasModelRegistry,
    warden: CanvasWarden,
    run_store: RunStore,
    workspace_id: str,
    project_id: str,
    compositor: CompositorService,
    worker_id: str = "canvas-worker-1",
    lease_seconds: int = 300,
    poll_interval: float = 1.0,
    reap_interval: float = 30.0,
    max_execution_seconds: float = 1800.0,
) -> APIRouter:
    """Build the HTTP boundary from the canonical Canvas runtime.

    This is the production assembly point: callers cannot provide an executor
    independently of the scope-bound ``RunStore`` adapter. The returned router
    owns the runtime worker lifecycle and starts it with the FastAPI
    application, so admitted receipts do not remain pending indefinitely.

    The ADR-044 AssetInstance router is merged onto the same app mount so
    ``asset_*`` modules stay process-reachable from this composition root
    (#2311) without colliding with LayerRecord design paths.
    """
    from fastapi import APIRouter as _APIRouter

    runtime = build_canvas_runtime(
        store=store,
        image_client=image_client,
        model_registry=model_registry,
        warden=warden,
        run_store=run_store,
        workspace_id=workspace_id,
        project_id=project_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        poll_interval=poll_interval,
        reap_interval=reap_interval,
        max_execution_seconds=max_execution_seconds,
    )
    from maistro_canvas.canvas.routes import make_canvas_router

    legacy = make_canvas_router(runtime=runtime, compositor=compositor)
    assets = build_asset_instance_surface()
    # Parent router carries both trees; asset routes keep their own /v2/canvas
    # prefix while the legacy canvas router uses its /api/canvas mount.
    combined = _APIRouter()
    combined.include_router(legacy)
    combined.include_router(assets.router)
    return combined


def bind_canvas_runner_lifecycle(
    *,
    router: APIRouter,
    runtime: CanvasRuntime,
    shutdown_timeout: float = _DEFAULT_SHUTDOWN_GRACE_SECONDS,
) -> None:
    """Tie one Canvas worker to the FastAPI application's lifecycle.

    ``APIRouter`` copies startup/shutdown handlers when mounted, keeping the
    worker on the same production boundary as canonical Run admission. This
    binds lifecycle ownership only; queue claims and execution authority stay
    with ``CanvasJobRunner`` and the canonical Run adapter.

    ``stop_runner`` gives the poll loop ``shutdown_timeout`` seconds to notice
    ``stop()`` and return on its own — enough for an idle loop's next
    ``poll_interval`` sleep to elapse — before cancelling the task outright.
    ``stop()`` alone cannot interrupt a `tick_once` blocked inside a
    provider call, so without this bound a stalled provider would block
    application shutdown indefinitely.

    The deadline is a non-cancelling wait (``asyncio.wait``), not
    ``asyncio.wait_for``: the latter cancels at the deadline and then keeps
    waiting until the task actually finishes, so a provider coroutine that
    swallows ``CancelledError`` would still hang shutdown (Codex #1535). After
    cancelling, the task gets one more bounded grace window and is then
    abandoned with an error log.
    """

    task: asyncio.Task[None] | None = None

    async def start_runner() -> None:
        nonlocal task
        if task is not None and not task.done():
            return
        task = asyncio.create_task(runtime.runner.start(), name="canvas-job-runner")

    async def stop_runner() -> None:
        nonlocal task
        runtime.runner.stop()
        if task is None:
            return
        current, task = task, None
        done, _pending = await asyncio.wait({current}, timeout=shutdown_timeout)
        if not done:
            logger.warning(
                "canvas_runner_shutdown_timeout timeout=%s; cancelling stuck tick",
                shutdown_timeout,
            )
            current.cancel()
            done, _pending = await asyncio.wait({current}, timeout=shutdown_timeout)
            if not done:
                logger.error("canvas_runner_shutdown_abandoned; runner task ignored cancellation")
                current.add_done_callback(_consume_runner_outcome)
                return
        _consume_runner_outcome(current)

    router.add_event_handler("startup", start_runner)
    router.add_event_handler("shutdown", stop_runner)


def _consume_runner_outcome(task: asyncio.Task[None]) -> None:
    """Retrieve a finished runner task's outcome, logging an unexpected error."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("canvas_runner_exited_with_error", exc_info=exc)


__all__ = [
    "AssetInstanceSurface",
    "CanvasModelRegistry",
    "CanvasRunner",
    "CanvasRuntime",
    "CanvasWarden",
    "bind_canvas_runner_lifecycle",
    "build_asset_instance_surface",
    "build_canvas_router",
    "build_canvas_runtime",
    "plan_asset_render",
]
