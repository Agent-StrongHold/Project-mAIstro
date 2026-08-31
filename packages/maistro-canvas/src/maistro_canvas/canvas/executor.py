"""Canvas tool executor — implements the five canvas actions.

Da Vinci and Fabulist agents call this via ToolDispatcher. The executor manages
Canvas-domain job receipts while physical generation is correlated to canonical
Run/NodeRun/Attempt evidence when a canonical execution binding is configured.

Error wrapping contract: raw provider exceptions never surface to callers.
_sanitise_error() strips stack traces and internal details, preserving only a
safe, actionable message.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar

from maistro_canvas.canvas.canonical_execution import (
    CanvasCanonicalExecution,
    canonical_run_id,
    correlate_run,
)
from maistro_canvas.types import (
    _IMAGE_GEN_ACTIONS,
    GenerationJobRecord,
    JobAction,
    JobAlreadyTerminalError,
    JobInProgressError,
    JobNotDoneError,
    JobNotFoundError,
    JobStatus,
    LayerType,
    PromptBlockedError,
    RefineNoSourceError,
    TextLayerNoGenError,
    UnknownModelError,
    VariantIndexOutOfRangeError,
)

if TYPE_CHECKING:
    from maistro_canvas.protocols import CanvasStore, ImageGenClient
    from maistro_canvas.types import CanvasRecord, LayerRecord

logger = logging.getLogger("maistro_canvas.canvas.executor")

_ACTIVE_STATUSES = frozenset({JobStatus.PENDING, JobStatus.RUNNING})
_TERMINAL_STATUSES = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})
_T = TypeVar("_T")


class _WardenProtocol:
    async def scan_prompt(self, prompt: str) -> str:
        raise NotImplementedError


class _ModelRegistryProtocol:
    def is_registered(self, model_id: str) -> bool:
        raise NotImplementedError

    def get_default_draft(self) -> str:
        raise NotImplementedError


def _sanitise_error(exc: Exception) -> str:
    """Return a safe error message — strips stack traces and raw provider bodies."""
    raw = str(exc)
    lower = raw.lower()
    if "429" in raw or "rate_limit" in lower or "too many" in lower or "ratelimit" in lower:
        return "Generation failed: rate limit reached. Try again in a moment."
    if "503" in raw or "service unavailable" in lower:
        return "Generation failed: provider service temporarily unavailable."
    if "401" in raw or "403" in raw or "unauthorized" in lower or "forbidden" in lower:
        return "Generation failed: provider authentication error."
    if "timeout" in lower or "timed out" in lower:
        return "Generation failed: provider request timed out."
    return "Generation failed: provider error. Please try again."


class CanvasExecutor:
    """Manages Canvas generation receipts and their physical execution.

    ``canonical_execution`` is a scope-bound adapter supplied by production
    composition after authorization. Direct ``run_job`` remains a compatibility
    surface for tests/CLI when no binding exists, but the background runner and
    shipped generation route require a canonical binding before provider work.
    """

    def __init__(
        self,
        *,
        store: CanvasStore,
        image_client: ImageGenClient,
        model_registry: _ModelRegistryProtocol,
        warden: _WardenProtocol,
        canonical_execution: CanvasCanonicalExecution | None = None,
    ) -> None:
        self._store = store
        self._image_client = image_client
        self._model_registry = model_registry
        self._warden = warden
        self._canonical_execution = canonical_execution
        self._layer_locks: dict[str, asyncio.Lock] = {}

    @property
    def canonical_enabled(self) -> bool:
        """Whether this executor can admit and execute canonical Canvas Runs."""
        return self._canonical_execution is not None

    def _layer_lock(self, layer_id: str) -> asyncio.Lock:
        if layer_id not in self._layer_locks:
            self._layer_locks[layer_id] = asyncio.Lock()
        return self._layer_locks[layer_id]

    async def start_job(
        self,
        *,
        canvas_id: str,
        layer_id: str,
        action: str,
        model_id: str | None = None,
        prompt: str = "",
        count: int = 1,
        seed: int | None = None,
        negative_prompt: str = "",
        region: str = "full",
        strength: float = 0.6,
        actor_principal_id: str | None = None,
    ) -> GenerationJobRecord:
        """Validate preconditions and enqueue a Canvas-domain generation receipt.

        When canonical execution is configured, admission happens only after all
        Canvas preconditions have passed and before the receipt is persisted, so
        the durable receipt can carry its canonical Run id in the existing JSON
        ``params`` column without a schema migration.
        """
        async with self._layer_lock(layer_id):
            return await self._start_job_locked(
                canvas_id=canvas_id,
                layer_id=layer_id,
                action=action,
                model_id=model_id,
                prompt=prompt,
                count=count,
                seed=seed,
                negative_prompt=negative_prompt,
                region=region,
                strength=strength,
                actor_principal_id=actor_principal_id,
            )

    async def _start_job_locked(
        self,
        *,
        canvas_id: str,
        layer_id: str,
        action: str,
        model_id: str | None,
        prompt: str,
        count: int,
        seed: int | None,
        negative_prompt: str,
        region: str,
        strength: float,
        actor_principal_id: str | None,
    ) -> GenerationJobRecord:
        layer = await self._store.get_layer(layer_id)
        if layer is None:
            from maistro_canvas.types import LayerNotFoundError

            raise LayerNotFoundError(f"layer {layer_id!r} not found")

        if layer.layer_type == LayerType.TEXT and action in _IMAGE_GEN_ACTIONS:
            raise TextLayerNoGenError(f"layer_type='text' does not support action={action!r}")

        resolved_model = model_id or self._model_registry.get_default_draft()
        if not self._model_registry.is_registered(resolved_model):
            raise UnknownModelError(f"model {resolved_model!r} is not registered")

        if prompt:
            verdict = await self._warden.scan_prompt(prompt)
            if verdict == "BLOCK":
                raise PromptBlockedError("prompt blocked by safety policy")

        if action == JobAction.REFINE and not layer.image_path:
            raise RefineNoSourceError(f"layer {layer_id!r} has no image_path; cannot refine")

        active = await self._store.active_job_for_layer(layer_id)
        if active is not None:
            raise JobInProgressError(
                f"layer {layer_id!r} already has an active job ({active.id!r})"
            )

        job = GenerationJobRecord(
            id=str(uuid.uuid4()),
            layer_id=layer_id,
            canvas_id=canvas_id,
            action=action,
            status=JobStatus.PENDING,
            model_id=resolved_model,
            prompt=prompt,
            params={
                "count": count,
                "seed": seed,
                "negative_prompt": negative_prompt,
                "region": region,
                "strength": strength,
            },
        )

        if self._canonical_execution is None:
            return await self._store.create_job(job)

        run_id = await self._canonical_execution.admit(
            job_id=job.id,
            canvas_id=canvas_id,
            layer_id=layer_id,
            action=action,
            actor_principal_id=actor_principal_id,
        )
        correlate_run(job.params, run_id)
        try:
            return await self._store.create_job(job)
        except BaseException:
            with contextlib.suppress(Exception):
                await self._canonical_execution.cancel(run_id)
            raise

    async def run_job(self, job_id: str) -> GenerationJobRecord:
        """Execute a pending job synchronously (compatibility path for tests/CLI)."""
        job = await self._store.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")
        if job.status != JobStatus.PENDING:
            logger.warning("run_job called on non-pending job %s (status=%s)", job_id, job.status)
            return job

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await self._store.update_job(job)

        try:
            result_paths = await self._execute_action(job)
            job.status = JobStatus.DONE
            job.result_paths = result_paths
            job.completed_at = datetime.now(UTC)
            logger.info("Job %s done: %d paths", job_id, len(result_paths))
        except Exception as exc:
            job.error_message = await self.fail_job_execution(job, exc)
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            logger.warning("Job %s failed: %s", job_id, exc)

        return await self._store.update_job(job)

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        """Execute one runner-claimed job with correlation integrity checks."""
        run_id = canonical_run_id(job.params)
        if run_id is None and self._canonical_execution is None:
            # Compatibility-only direct call. CanvasJobRunner rejects a real
            # CanvasExecutor with canonical_enabled=False before it claims work.
            job.result_paths = await self._execute_action(job)
            return
        if run_id is None:
            raise RuntimeError(
                f"Canvas job {job.id!r} has canonical execution configured but no Run correlation"
            )
        if self._canonical_execution is None:
            raise RuntimeError(
                f"Canvas job {job.id!r} names canonical Run {run_id!r} but no adapter is bound"
            )
        job.result_paths = await self._execute_action(job)

    async def fail_job_execution(self, job: GenerationJobRecord, exc: Exception) -> str:
        """Sanitize a terminal provider error and reconcile its canonical Run."""
        safe_error = _sanitise_error(exc)
        run_id = canonical_run_id(job.params)
        if run_id is not None:
            if self._canonical_execution is None:
                raise RuntimeError(
                    f"Canvas job {job.id!r} names canonical Run {run_id!r} but no adapter is bound"
                )
            await self._canonical_execution.fail(run_id, safe_error)
        return safe_error

    async def _execute_action(self, job: GenerationJobRecord) -> list[str]:
        """Dispatch to the correct image-gen action; return signed URL list."""
        canvas = await self._store.get_canvas(job.canvas_id)
        if canvas is None:
            from maistro_canvas.types import CanvasNotFoundError

            raise CanvasNotFoundError(f"canvas {job.canvas_id!r} not found")

        if job.action == JobAction.GENERATE:
            return await self._execute_generate(job, canvas)
        if job.action == JobAction.REFINE:
            return await self._execute_refine(job)
        if job.action == JobAction.REFERENCE:
            return await self._execute_reference(job, canvas)

        msg = f"action {job.action!r} is not an image-gen action"
        raise ValueError(msg)

    async def _execute_stage(
        self,
        job: GenerationJobRecord,
        stage: str,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        run_id = canonical_run_id(job.params)
        if run_id is None:
            if self._canonical_execution is not None:
                raise RuntimeError(
                    f"Canvas job {job.id!r} has canonical execution configured but no Run correlation"
                )
            # Compatibility-only direct path. CanvasJobRunner checks
            # canonical_enabled before claim, so shipped background execution
            # cannot silently bypass canonical evidence.
            return await operation()
        if self._canonical_execution is None:
            raise RuntimeError(
                f"Canvas job {job.id!r} names canonical Run {run_id!r} but no adapter is bound"
            )
        return await self._canonical_execution.execute_stage(run_id, stage, operation)

    async def _execute_generate(self, job: GenerationJobRecord, canvas: CanvasRecord) -> list[str]:
        params = job.params
        count = int(params.get("count", 1))
        seed = params.get("seed")
        negative_prompt = str(params.get("negative_prompt", ""))

        async def _generate() -> list[str]:
            images = await self._image_client.generate(
                model_id=job.model_id,
                prompt=job.prompt,
                width=canvas.width,
                height=canvas.height,
                count=count,
                seed=seed,
                negative_prompt=negative_prompt,
            )
            paths = [img.url for img in images if img.url]
            if not paths:
                raise ValueError("Provider returned no usable image URLs (IMAGE_DECODE_ERROR)")
            if len(paths) != count:
                logger.warning(
                    "Expected %d images, got %d valid URLs for job %s",
                    count,
                    len(paths),
                    job.id,
                )
            return paths

        return await self._execute_stage(job, "generate", _generate)

    async def _execute_refine(self, job: GenerationJobRecord) -> list[str]:
        params = job.params
        layer = await self._store.get_layer(job.layer_id)
        if layer is None:
            from maistro_canvas.types import RefineNoSourceError

            raise RefineNoSourceError("source image no longer available")
        source_image_url = layer.image_path
        if not source_image_url:
            from maistro_canvas.types import RefineNoSourceError

            raise RefineNoSourceError("source image no longer available")

        async def _refine() -> list[str]:
            refined = await self._image_client.refine(
                model_id=job.model_id,
                source_url=source_image_url,
                prompt=job.prompt,
                region=str(params.get("region", "full")),
                strength=float(params.get("strength", 0.6)),
            )
            return [refined.url] if refined.url else []

        return await self._execute_stage(job, "refine", _refine)

    async def _execute_reference(self, job: GenerationJobRecord, canvas: CanvasRecord) -> list[str]:
        seed = job.params.get("seed")

        async def _hero() -> list[str]:
            hero_list = await self._image_client.generate(
                model_id=job.model_id,
                prompt=job.prompt + " front view, isolated on white background",
                width=canvas.width,
                height=canvas.height,
                count=1,
                seed=seed,
            )
            hero_url = hero_list[0].url if hero_list else ""
            return [hero_url] if hero_url else []

        hero_paths = await self._execute_stage(job, "reference.hero", _hero)
        if not hero_paths:
            return []
        hero_url = hero_paths[0]
        paths = [hero_url]
        for stage, angle in (
            ("reference.side", "side view"),
            ("reference.back", "back view"),
            ("reference.three-quarter", "3/4 view"),
        ):

            async def _view(angle: str = angle) -> list[str]:
                view = await self._image_client.refine(
                    model_id=job.model_id,
                    source_url=hero_url,
                    prompt=f"{job.prompt} {angle}, isolated on white background",
                    region="full",
                    strength=0.7,
                )
                return [view.url] if view.url else []

            view_paths = await self._execute_stage(job, stage, _view)
            paths.extend(view_paths)
        return paths

    async def accept_variant(
        self,
        job_id: str,
        variant_index: int,
    ) -> tuple[GenerationJobRecord, LayerRecord]:
        """Accept a generated variant: update layer.image_path atomically."""
        job = await self._store.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")

        if job.status != JobStatus.DONE:
            raise JobNotDoneError(
                f"job {job_id!r} is in status={job.status!r}; must be 'done' to accept"
            )

        if variant_index < 0 or variant_index >= len(job.result_paths):
            raise VariantIndexOutOfRangeError(
                f"variant_index={variant_index} out of range [0, {len(job.result_paths) - 1}]"
            )

        layer = await self._store.get_layer(job.layer_id)
        if layer is None:
            from maistro_canvas.types import LayerNotFoundError

            raise LayerNotFoundError(f"layer {job.layer_id!r} not found")

        layer.image_path = job.result_paths[variant_index]
        layer.updated_at = datetime.now(UTC)
        updated_layer = await self._store.update_layer(layer)

        job.selected_index = variant_index
        updated_job = await self._store.update_job(job)

        canvas = await self._store.get_canvas(job.canvas_id)
        if canvas is not None:
            canvas.updated_at = datetime.now(UTC)
            await self._store.update_canvas(canvas)

        return updated_job, updated_layer

    async def cancel_job(self, job_id: str) -> GenerationJobRecord:
        """Cancel a pending or running Canvas receipt and its canonical execution."""
        job = await self._store.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")

        if job.is_terminal():
            raise JobAlreadyTerminalError(
                f"job {job_id!r} is already in terminal status={job.status!r}"
            )

        run_id = canonical_run_id(job.params)
        if run_id is not None:
            if self._canonical_execution is None:
                raise RuntimeError(
                    f"Canvas job {job.id!r} names canonical Run {run_id!r} but no adapter is bound"
                )
            await self._canonical_execution.cancel(run_id)

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        return await self._store.update_job(job)
