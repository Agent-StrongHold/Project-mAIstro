"""Canvas tool executor — implements the five canvas actions.

Da Vinci and Fabulist agents call this via ToolDispatcher.  The
executor manages job lifecycle (create → run → accept/cancel) and
enforces all invariants from spec 1189 before touching the store.

Error wrapping contract: raw provider exceptions never surface to
callers.  _sanitise_error() strips stack traces and internal details,
preserving only a safe, actionable message.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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


# ────────────────────────���─────────────────��──────────────────────────
# Warden protocol (minimal — only scan_prompt used here)
# ─────────────────────────────────────────────────────────────────────


class _WardenProtocol:
    async def scan_prompt(self, prompt: str) -> str:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────
# Model registry protocol
# ─────────────────────────────────────────────���───────────────────────


class _ModelRegistryProtocol:
    def is_registered(self, model_id: str) -> bool:
        raise NotImplementedError

    def get_default_draft(self) -> str:
        raise NotImplementedError


# ────────────────────────────��───────────────────────��────────────────
# Error sanitiser
# ─────────────────────────────────────────────────────────────────────


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
    # Generic fallback — do not include raw message
    return "Generation failed: provider error. Please try again."


# ─────────────────────────────��─────────────────────────────���─────────
# CanvasExecutor
# ─────────────────────────────────────────────────────────────────────


class CanvasExecutor:
    """Manages canvas generation jobs end-to-end."""

    def __init__(
        self,
        *,
        store: CanvasStore,
        image_client: ImageGenClient,
        model_registry: _ModelRegistryProtocol,
        warden: _WardenProtocol,
    ) -> None:
        self._store = store
        self._image_client = image_client
        self._model_registry = model_registry
        self._warden = warden
        # Per-layer lock to prevent concurrent start_job races in-process.
        # Production uses a DB advisory lock; this covers the in-memory path.
        self._layer_locks: dict[str, asyncio.Lock] = {}

    def _layer_lock(self, layer_id: str) -> asyncio.Lock:
        if layer_id not in self._layer_locks:
            self._layer_locks[layer_id] = asyncio.Lock()
        return self._layer_locks[layer_id]

    # ── Public API ──────────────────────────────��─────────────────────

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
    ) -> GenerationJobRecord:
        """Validate pre-conditions and enqueue a generation job.

        Returns a persisted GenerationJobRecord with status=pending.
        Raises a domain error (CanvasError subclass) on any violation.
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
    ) -> GenerationJobRecord:
        layer = await self._store.get_layer(layer_id)
        if layer is None:
            from maistro_canvas.types import LayerNotFoundError

            raise LayerNotFoundError(f"layer {layer_id!r} not found")

        # Pre-condition: text layers cannot use image generation actions
        if layer.layer_type == LayerType.TEXT and action in _IMAGE_GEN_ACTIONS:
            raise TextLayerNoGenError(f"layer_type='text' does not support action={action!r}")

        # Pre-condition: resolve and validate model
        resolved_model = model_id or self._model_registry.get_default_draft()
        if not self._model_registry.is_registered(resolved_model):
            raise UnknownModelError(f"model {resolved_model!r} is not registered")

        # Pre-condition: warden scan
        if prompt:
            verdict = await self._warden.scan_prompt(prompt)
            if verdict == "BLOCK":
                raise PromptBlockedError("prompt blocked by safety policy")

        # Pre-condition: refine requires existing image
        if action == JobAction.REFINE and not layer.image_path:
            raise RefineNoSourceError(f"layer {layer_id!r} has no image_path; cannot refine")

        # Pre-condition: no active job for this layer (checked inside lock)
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
        return await self._store.create_job(job)

    async def run_job(self, job_id: str) -> GenerationJobRecord:
        """Execute a pending job synchronously (used in tests and CLI).

        In production, a background task runner calls this after start_job.
        """
        job = await self._store.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")
        if job.status != JobStatus.PENDING:
            logger.warning("run_job called on non-pending job %s (status=%s)", job_id, job.status)
            return job

        # Transition to running
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
            job.status = JobStatus.FAILED
            job.error_message = _sanitise_error(exc)
            job.completed_at = datetime.now(UTC)
            logger.warning("Job %s failed: %s", job_id, exc)

        return await self._store.update_job(job)

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        """Execute an already-claimed job (CanvasJobRunner contract).

        The runner owns status/lease transitions and persistence; this only
        performs the action and records the result paths on the job.
        """
        job.result_paths = await self._execute_action(job)

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

        # Composite and text are handled elsewhere
        msg = f"action {job.action!r} is not an image-gen action"
        raise ValueError(msg)

    async def _execute_generate(self, job: GenerationJobRecord, canvas: CanvasRecord) -> list[str]:
        params = job.params
        count: int = int(params.get("count", 1))
        seed: int | None = params.get("seed")  # 0 is valid, None means unset
        negative_prompt: str = str(params.get("negative_prompt", ""))
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
            # No valid URLs — treat as a decode/provider error
            msg = "Provider returned no usable image URLs (IMAGE_DECODE_ERROR)"
            raise ValueError(msg)
        if len(paths) != count:
            logger.warning(
                "Expected %d images, got %d valid URLs for job %s",
                count,
                len(paths),
                job.id,
            )
        return paths

    async def _execute_refine(self, job: GenerationJobRecord) -> list[str]:
        params = job.params
        layer = await self._store.get_layer(job.layer_id)
        if layer is None or not layer.image_path:
            from maistro_canvas.types import RefineNoSourceError

            raise RefineNoSourceError("source image no longer available")
        refined = await self._image_client.refine(
            model_id=job.model_id,
            source_url=layer.image_path,
            prompt=job.prompt,
            region=str(params.get("region", "full")),
            strength=float(params.get("strength", 0.6)),
        )
        return [refined.url] if refined.url else []

    async def _execute_reference(self, job: GenerationJobRecord, canvas: CanvasRecord) -> list[str]:
        params = job.params
        seed: int | None = params.get("seed")  # 0 is valid, None means unset
        # Generate hero image then three turnaround views
        hero_list = await self._image_client.generate(
            model_id=job.model_id,
            prompt=job.prompt + " front view, isolated on white background",
            width=canvas.width,
            height=canvas.height,
            count=1,
            seed=seed,
        )
        hero_url = hero_list[0].url if hero_list else ""
        if not hero_url:
            return []
        views = []
        for angle in ("side view", "back view", "3/4 view"):
            v = await self._image_client.refine(
                model_id=job.model_id,
                source_url=hero_url,
                prompt=f"{job.prompt} {angle}, isolated on white background",
                region="full",
                strength=0.7,
            )
            if v.url:
                views.append(v.url)
        return [hero_url, *views]

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

        # Explicit bounds check — no negative index tricks
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

        # Advance canvas.updated_at (invariant: canvas_updated_on_layer_accept)
        canvas = await self._store.get_canvas(job.canvas_id)
        if canvas is not None:
            canvas.updated_at = datetime.now(UTC)
            await self._store.update_canvas(canvas)

        return updated_job, updated_layer

    async def cancel_job(self, job_id: str) -> GenerationJobRecord:
        """Cancel a pending or running job."""
        job = await self._store.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} not found")

        if job.is_terminal():
            raise JobAlreadyTerminalError(
                f"job {job_id!r} is already in terminal status={job.status!r}"
            )

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        return await self._store.update_job(job)
