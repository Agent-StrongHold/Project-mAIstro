"""Production composition for Canvas canonical generation execution.

The outer application supplies an already-authorized canonical scope and the
Canvas-domain providers. This module is the package-owned construction seam so
production cannot accidentally create a CanvasExecutor without the canonical
Run -> NodeRun -> Attempt adapter.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from maistro.runs.store import RunStore
from maistro_canvas.canvas.canonical_execution import CanvasCanonicalExecution
from maistro_canvas.canvas.executor import CanvasExecutor
from maistro_canvas.protocols import CanvasStore, ImageGenClient

if TYPE_CHECKING:
    from fastapi import APIRouter

    from maistro_canvas.protocols import CompositorService


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
    )
    return CanvasRuntime(
        store=store,
        canonical_execution=canonical,
        executor=executor,
        runner=runner,
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
) -> APIRouter:
    """Build the HTTP boundary from the canonical Canvas runtime.

    This is the production assembly point: callers cannot provide an executor
    independently of the scope-bound ``RunStore`` adapter. Applications that
    also run the worker retain a ``CanvasRuntime`` from
    :func:`build_canvas_runtime` and start its runner in their lifecycle.
    """
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
    )
    from maistro_canvas.canvas.routes import make_canvas_router

    return make_canvas_router(runtime=runtime, compositor=compositor)


__all__ = [
    "CanvasModelRegistry",
    "CanvasRunner",
    "CanvasRuntime",
    "CanvasWarden",
    "build_canvas_router",
    "build_canvas_runtime",
]
