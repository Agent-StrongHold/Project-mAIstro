"""Production composition for Canvas canonical generation execution.

The outer application supplies an already-authorized canonical scope and the
Canvas-domain providers. This module is the package-owned construction seam so
production cannot accidentally create a CanvasExecutor without the canonical
Run -> NodeRun -> Attempt adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from maistro.runs.store import RunStore
from maistro_canvas.canvas.canonical_execution import CanvasCanonicalExecution
from maistro_canvas.canvas.executor import CanvasExecutor
from maistro_canvas.canvas.runner import CanvasJobRunner
from maistro_canvas.protocols import CanvasStore, ImageGenClient


class CanvasModelRegistry(Protocol):
    """Model validation/default selection required by CanvasExecutor."""

    def is_registered(self, model_id: str) -> bool: ...

    def get_default_draft(self) -> str: ...


class CanvasWarden(Protocol):
    """Prompt policy dependency required by CanvasExecutor."""

    async def scan_prompt(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class CanvasRuntime:
    """The one Canvas execution binding used by routes and its worker."""

    canonical_execution: CanvasCanonicalExecution
    executor: CanvasExecutor
    runner: CanvasJobRunner


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
    runner = CanvasJobRunner(
        store=store,
        executor=executor,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        poll_interval=poll_interval,
        reap_interval=reap_interval,
    )
    return CanvasRuntime(canonical_execution=canonical, executor=executor, runner=runner)


__all__ = [
    "CanvasModelRegistry",
    "CanvasRuntime",
    "CanvasWarden",
    "build_canvas_runtime",
]
