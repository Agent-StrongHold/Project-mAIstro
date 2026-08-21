"""Canvas Studio REST API (spec 1189).

All routes go through make_canvas_router() so tests can inject fakes
without touching app.state.  Production wires real deps via the DI
container.

Route summary:
  POST   /api/canvas                              create canvas
  GET    /api/canvas                              list canvases
  GET    /api/canvas/{id}                         get canvas + layers
  PATCH  /api/canvas/{id}                         update canvas
  DELETE /api/canvas/{id}                         soft-delete canvas

  POST   /api/canvas/{id}/layers                  add layer
  GET    /api/canvas/{id}/layers                  list layers
  PATCH  /api/canvas/{id}/layers/{lid}            update layer
  DELETE /api/canvas/{id}/layers/{lid}            remove layer
  POST   /api/canvas/{id}/layers/reorder          reorder layers

  POST   /api/canvas/{id}/layers/{lid}/generate   start generation job
  GET    /api/canvas/{id}/layers/{lid}/jobs        list layer jobs
  GET    /api/canvas/jobs/{jid}                   get job
  DELETE /api/canvas/jobs/{jid}                   cancel job
  POST   /api/canvas/jobs/{jid}/accept/{variant}  accept variant

  POST   /api/canvas/{id}/composite               composite layers
  GET    /api/canvas/{id}/composite/latest        latest composite

  GET    /api/canvas/{id}/export                  export image
  GET    /api/canvas/models                       list models
"""

# B008 (function-call-in-default-argument) is the standard FastAPI
# dependency-injection pattern (Depends(...), Query(...)); see the
# sibling asset_routes.py for the same suppression.
# ruff: noqa: B008

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from maistro_canvas.auth import CurrentUser, get_current_user
from maistro_canvas.types import (
    _MAX_GENERATE_COUNT,
    _VALID_EXPORT_FORMATS,
    CanvasArchivedError,
    CanvasError,
    CanvasHasLayersError,
    CanvasNotFoundError,
    DuplicateZIndexError,
    IncompleteReorderError,
    JobAlreadyTerminalError,
    JobInProgressError,
    JobNotDoneError,
    JobNotFoundError,
    LayerLimitExceededError,
    LayerLockedError,
    LayerNotFoundError,
    PromptBlockedError,
    RefineNoSourceError,
    TextLayerNoGenError,
    UnknownModelError,
    UnsupportedFormatError,
    VariantIndexOutOfRangeError,
    normalise_rotation,
    validate_canvas_dimensions,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from maistro_canvas.canvas.executor import CanvasExecutor
    from maistro_canvas.protocols import CanvasStore, CompositorService
    from maistro_canvas.types import CanvasRecord, GenerationJobRecord, LayerRecord

logger = logging.getLogger("maistro_canvas.canvas.routes")

_POSITIONAL_FIELDS = frozenset({"x", "y", "scale", "rotation", "opacity"})

# Simple body-field → (attribute, converter) updates for a layer.
_SIMPLE_LAYER_FIELDS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "name": ("name", str),
    "x": ("x", float),
    "y": ("y", float),
    "scale": ("scale", float),
    "blend_mode": ("blend_mode", str),
    "visible": ("visible", bool),
    "locked": ("locked", bool),
    "tier": ("tier", str),
}
# Fields that map None through unchanged and stringify otherwise.
_NULLABLE_STR_LAYER_FIELDS: dict[str, str] = {
    "prompt": "prompt",
    "negative_prompt": "negative_prompt",
    "model_id": "model_id",
}


_ERROR_STATUS_MAP: dict[type, int] = {
    CanvasNotFoundError: 404,
    LayerNotFoundError: 404,
    JobNotFoundError: 404,
    CanvasArchivedError: 410,
    CanvasHasLayersError: 409,
    LayerLimitExceededError: 409,
    LayerLockedError: 409,
    JobInProgressError: 409,
    JobAlreadyTerminalError: 409,
    JobNotDoneError: 409,
    TextLayerNoGenError: 400,
    UnknownModelError: 400,
    PromptBlockedError: 400,
    RefineNoSourceError: 400,
    UnsupportedFormatError: 400,
    DuplicateZIndexError: 422,
    IncompleteReorderError: 422,
    VariantIndexOutOfRangeError: 422,
}


def _error(exc: CanvasError) -> JSONResponse:
    """Map a domain error to a JSON error response.

    The detail field is sanitised: raw stack traces are stripped so
    internal provider details never reach the client.
    """
    safe_detail = exc.detail
    if "Traceback" in safe_detail or "stack" in safe_detail:
        safe_detail = f"{exc.code}: request could not be completed"
    status = _ERROR_STATUS_MAP.get(type(exc), 400)
    return JSONResponse(
        status_code=status,
        content={"code": exc.code, "detail": safe_detail},
    )


def _resolve_dimensions(body: dict[str, Any]) -> tuple[int, int]:
    """Resolve canvas (width, height) from a create-body, honouring aspect_ratio."""
    if "aspect_ratio" in body and "width" not in body and "height" not in body:
        pair = _ASPECT_RATIO_BASES.get(str(body["aspect_ratio"]))
        if pair is None:
            raise HTTPException(status_code=422, detail="unknown aspect_ratio shorthand")
        return pair
    return int(body.get("width", 1024)), int(body.get("height", 1024))


def _validation_error_response(exc: ValueError, org_id: str) -> JSONResponse:
    """Build a field-level 422 response for a dimension validation failure."""
    raw_msg = str(exc)
    code = "NOT_DIVISIBLE_BY_8" if "divisible" in raw_msg else "OUT_OF_RANGE"
    field = "width" if "width" in raw_msg else "height"
    safe_msg = (
        "dimension must be divisible by 8"
        if code == "NOT_DIVISIBLE_BY_8"
        else "dimension is out of allowed range"
    )
    logger.warning(
        "Canvas dimension validation failed for org_id=%s field=%s code=%s",
        org_id,
        field,
        code,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=422,
        content={"detail": [{"field": field, "code": code, "msg": safe_msg}]},
    )


async def _require_canvas(store: CanvasStore, canvas_id: str, org_id: str) -> CanvasRecord:
    """Fetch a canvas for the caller's org or raise the right HTTP error."""
    canvas = await store.get_canvas(canvas_id)
    if canvas is None or canvas.org_id != org_id:
        raise HTTPException(status_code=404)
    if canvas.is_archived():
        raise HTTPException(status_code=410)
    return canvas


_EXPORT_MEDIA_TYPES: dict[str, str] = {
    "png": "image/png",
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


async def _export_image(
    store: CanvasStore,
    compositor: CompositorService,
    canvas: CanvasRecord,
    canvas_id: str,
    fmt: str,
    quality: int,
) -> Response:
    """Composite (on demand) and encode a canvas to the requested image format."""
    # Composite on-demand if nothing stored
    comp = await store.latest_composite(canvas_id)
    if comp is None:
        layers = await store.list_layers(canvas_id)
        comp = await compositor.composite(canvas, layers)
        await store.save_composite(comp)

    # Re-encode to the requested format
    from maistro_canvas.canvas.compositor import PilCompositorService

    if isinstance(compositor, PilCompositorService):
        output_bytes = await compositor.encode(comp.image_bytes, fmt=fmt, quality=quality)
    else:
        output_bytes = comp.image_bytes  # fallback: return raw PNG

    media_type = _EXPORT_MEDIA_TYPES.get(fmt, "image/png")
    filename = f"canvas-{canvas_id[:8]}.{fmt}"
    return Response(
        content=output_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _cancel_active_jobs(store: CanvasStore, executor: CanvasExecutor, canvas_id: str) -> None:
    """Best-effort cancel of any active jobs on a canvas before archiving."""
    layers = await store.list_layers(canvas_id)
    for lyr in layers:
        active = await store.active_job_for_layer(lyr.id)
        if active is not None:
            with contextlib.suppress(Exception):
                await executor.cancel_job(active.id)


async def _require_layer(store: CanvasStore, canvas_id: str, layer_id: str) -> LayerRecord:
    """Fetch a layer that belongs to ``canvas_id`` or raise 404."""
    layer = await store.get_layer(layer_id)
    if layer is None or layer.canvas_id != canvas_id:
        raise HTTPException(status_code=404)
    return layer


async def _require_job(store: CanvasStore, job_id: str, org_id: str) -> GenerationJobRecord:
    """Fetch a job and verify its canvas belongs to ``org_id`` or raise 404."""
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404)
    canvas = await store.get_canvas(job.canvas_id)
    if canvas is None or canvas.org_id != org_id:
        raise HTTPException(status_code=404)
    return job


def _apply_canvas_updates(canvas: CanvasRecord, body: dict[str, Any]) -> None:
    """Apply validated name/colour/dimension updates onto ``canvas`` in place."""
    if "name" in body:
        canvas.name = str(body["name"]).strip() or canvas.name
    if "background_color" in body:
        canvas.background_color = str(body["background_color"])
    if "width" in body or "height" in body:
        new_w = int(body.get("width", canvas.width))
        new_h = int(body.get("height", canvas.height))
        try:
            validate_canvas_dimensions(new_w, new_h)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        canvas.width = new_w
        canvas.height = new_h


def _apply_layer_updates(layer: LayerRecord, body: dict[str, Any]) -> None:
    """Apply validated field updates from ``body`` onto ``layer`` in place."""
    for key, (attr, convert) in _SIMPLE_LAYER_FIELDS.items():
        if key in body:
            setattr(layer, attr, convert(body[key]))
    if "rotation" in body:
        layer.rotation = normalise_rotation(float(body["rotation"]))
    if "opacity" in body:
        op = float(body["opacity"])
        if not (0.0 <= op <= 1.0):
            raise HTTPException(status_code=422, detail="opacity must be in [0.0, 1.0]")
        layer.opacity = op
    for key, attr in _NULLABLE_STR_LAYER_FIELDS.items():
        if key in body:
            value = body[key]
            setattr(layer, attr, str(value) if value is not None else None)


_ASPECT_RATIO_BASES: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1824, 1024),
    "9:16": (1024, 1824),
    "3:2": (1536, 1024),
    "2:3": (1024, 1536),
    "4:3": (1360, 1024),
    "3:4": (1024, 1360),
}


# ─────────────────────────────────────────────────────────────────────
# Factory — injects deps so tests can override cleanly
# ─────────────────────────────────────────────────────────────────────


def make_canvas_router(
    *,
    store: CanvasStore,
    executor: CanvasExecutor,
    compositor: CompositorService,
) -> APIRouter:
    """Return a router with the given dependencies closed over."""
    router = APIRouter()
    _register_canvas_routes(router, store, executor, compositor)
    _register_layer_routes(router, store, executor, compositor)
    _register_job_routes(router, store, executor, compositor)
    _register_composite_routes(router, store, executor, compositor)
    _register_export_routes(router, store, executor, compositor)
    return router


def _register_canvas_routes(
    router: APIRouter,
    store: CanvasStore,
    executor: CanvasExecutor,
    compositor: CompositorService,
) -> None:
    # ── Canvas CRUD ────────────────────────────────────────────────────

    @router.post("")
    async def create_canvas(
        body: dict[str, Any],
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        # Resolve dimensions
        width, height = _resolve_dimensions(body)

        try:
            validate_canvas_dimensions(width, height)
        except ValueError as exc:
            # Surface field-level 422 with NOT_DIVISIBLE_BY_8 or range errors
            return _validation_error_response(exc, auth.org_id)

        name = str(body.get("name", "Untitled Canvas")).strip()
        if not name:
            raise HTTPException(status_code=422, detail="name is required")

        canvas = await store.create_canvas(
            name=name,
            width=width,
            height=height,
            background_color=str(body.get("background_color", "#FFFFFF")),
            org_id=auth.org_id,
        )
        return JSONResponse(status_code=201, content=canvas.to_dict())

    @router.get("")
    async def list_canvases(
        auth: CurrentUser = Depends(get_current_user),
        include_archived: bool = Query(default=False),
    ) -> JSONResponse:
        canvases = await store.list_canvases(auth.org_id, include_archived=include_archived)
        return JSONResponse(content=[c.to_dict() for c in canvases])

    @router.get("/{canvas_id}")
    async def get_canvas(
        canvas_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        canvas = await _require_canvas(store, canvas_id, auth.org_id)
        layers = await store.list_layers(canvas_id)
        data = canvas.to_dict()
        data["layers"] = [lyr.to_dict() for lyr in layers]
        return JSONResponse(content=data)

    @router.patch("/{canvas_id}")
    async def update_canvas(
        canvas_id: str,
        body: dict[str, Any],
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        canvas = await _require_canvas(store, canvas_id, auth.org_id)

        # Reject dimension change if layers exist
        if ("width" in body or "height" in body) and canvas.layer_count > 0:
            return _error(CanvasHasLayersError("cannot resize canvas with existing layers"))

        _apply_canvas_updates(canvas, body)

        updated = await store.update_canvas(canvas)
        return JSONResponse(content=updated.to_dict())

    @router.delete("/{canvas_id}")
    async def delete_canvas(
        canvas_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        canvas = await store.get_canvas(canvas_id)
        if canvas is None or canvas.org_id != auth.org_id:
            raise HTTPException(status_code=404)

        # Cancel any active jobs on this canvas before archiving
        await _cancel_active_jobs(store, executor, canvas_id)

        canvas.archived_at = datetime.now(UTC)
        await store.update_canvas(canvas)
        return JSONResponse(content={"archived": True, "id": canvas_id})


def _register_layer_routes(
    router: APIRouter,
    store: CanvasStore,
    executor: CanvasExecutor,
    compositor: CompositorService,
) -> None:
    # ── Layer CRUD ─────────────────────────────────────────────────────

    @router.post("/{canvas_id}/layers")
    async def add_layer(
        canvas_id: str,
        body: dict[str, Any],
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        try:
            layer = await store.add_layer(
                canvas_id,
                name=str(body.get("name", "Layer")).strip(),
                layer_type=str(body.get("layer_type", "background")),
                z_index=body.get("z_index"),
                x=float(body.get("x", 0.0)),
                y=float(body.get("y", 0.0)),
                scale=float(body.get("scale", 1.0)),
                rotation=normalise_rotation(float(body.get("rotation", 0.0))),
                opacity=float(body.get("opacity", 1.0)),
                blend_mode=str(body.get("blend_mode", "normal")),
                visible=bool(body.get("visible", True)),
                locked=bool(body.get("locked", False)),
            )
        except LayerLimitExceededError as exc:
            return _error(exc)
        return JSONResponse(status_code=201, content=layer.to_dict())

    @router.get("/{canvas_id}/layers")
    async def list_layers(
        canvas_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        layers = await store.list_layers(canvas_id)
        return JSONResponse(content=[lyr.to_dict() for lyr in layers])

    @router.patch("/{canvas_id}/layers/{layer_id}")
    async def update_layer(
        canvas_id: str,
        layer_id: str,
        body: dict[str, Any],
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        layer = await _require_layer(store, canvas_id, layer_id)

        # Lock guard: positional fields forbidden on locked layers
        positional_changes = _POSITIONAL_FIELDS.intersection(body)
        if layer.locked and positional_changes:
            return _error(
                LayerLockedError(
                    f"layer {layer_id!r} is locked; cannot change {sorted(positional_changes)}"
                )
            )

        # Validate scale > 0
        if "scale" in body and float(body["scale"]) <= 0.0:
            raise HTTPException(status_code=422, detail="scale must be greater than 0")

        _apply_layer_updates(layer, body)

        updated = await store.update_layer(layer)
        return JSONResponse(content=updated.to_dict())

    @router.delete("/{canvas_id}/layers/{layer_id}")
    async def delete_layer(
        canvas_id: str,
        layer_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        await _require_layer(store, canvas_id, layer_id)
        await store.remove_layer(layer_id)
        return JSONResponse(content={"deleted": True, "id": layer_id})

    @router.post("/{canvas_id}/layers/reorder")
    async def reorder_layers(
        canvas_id: str,
        assignments: list[dict[str, Any]],
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        try:
            layers = await store.reorder_layers(canvas_id, assignments)
        except (DuplicateZIndexError, IncompleteReorderError) as exc:
            return _error(exc)
        return JSONResponse(content=[lyr.to_dict() for lyr in layers])


def _register_job_routes(  # noqa: C901  route-registration closure: independent handlers, one per endpoint
    router: APIRouter,
    store: CanvasStore,
    executor: CanvasExecutor,
    compositor: CompositorService,
) -> None:
    # ── Generation jobs ────────────────────────────────────────────────

    @router.post("/{canvas_id}/layers/{layer_id}/generate")
    async def start_generate(
        canvas_id: str,
        layer_id: str,
        body: dict[str, Any],
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        await _require_layer(store, canvas_id, layer_id)

        count = int(body.get("count", 1))
        if not (1 <= count <= _MAX_GENERATE_COUNT):
            raise HTTPException(
                status_code=422,
                detail=f"count must be between 1 and {_MAX_GENERATE_COUNT}",
            )

        try:
            job = await executor.start_job(
                canvas_id=canvas_id,
                layer_id=layer_id,
                action=str(body.get("action", "generate")),
                model_id=body.get("model_id"),
                prompt=str(body.get("prompt", "")),
                count=count,
                seed=body.get("seed"),
                negative_prompt=str(body.get("negative_prompt", "")),
                region=str(body.get("region", "full")),
                strength=float(body.get("strength", 0.6)),
            )
        except (
            TextLayerNoGenError,
            JobInProgressError,
            UnknownModelError,
            PromptBlockedError,
            RefineNoSourceError,
        ) as exc:
            return _error(exc)

        return JSONResponse(
            status_code=202,
            content={"job_id": job.id, "status": job.status},
        )

    @router.get("/{canvas_id}/layers/{layer_id}/jobs")
    async def list_layer_jobs(
        canvas_id: str,
        layer_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_canvas(store, canvas_id, auth.org_id)
        await _require_layer(store, canvas_id, layer_id)
        jobs = await store.list_jobs_for_layer(layer_id)
        return JSONResponse(content=[j.to_dict() for j in jobs])

    @router.get("/jobs/{job_id}")
    async def get_job(
        job_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        job = await _require_job(store, job_id, auth.org_id)
        return JSONResponse(content=job.to_dict())

    @router.delete("/jobs/{job_id}")
    async def cancel_job(
        job_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_job(store, job_id, auth.org_id)
        try:
            updated = await executor.cancel_job(job_id)
        except JobAlreadyTerminalError as exc:
            return _error(exc)
        return JSONResponse(content=updated.to_dict())

    @router.post("/jobs/{job_id}/accept/{variant_index}")
    async def accept_variant(
        job_id: str,
        variant_index: int,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        await _require_job(store, job_id, auth.org_id)
        try:
            updated_job, updated_layer = await executor.accept_variant(job_id, variant_index)
        except (JobNotDoneError, JobAlreadyTerminalError) as exc:
            return _error(exc)
        except VariantIndexOutOfRangeError as exc:
            return _error(exc)
        return JSONResponse(
            content={"job": updated_job.to_dict(), "layer": updated_layer.to_dict()}
        )


def _register_composite_routes(
    router: APIRouter,
    store: CanvasStore,
    executor: CanvasExecutor,
    compositor: CompositorService,
) -> None:
    # ── Compositing ────────────────────────────────────────────────────

    @router.post("/{canvas_id}/composite")
    async def composite_canvas(
        canvas_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        canvas = await _require_canvas(store, canvas_id, auth.org_id)
        layers = await store.list_layers(canvas_id)
        result = await compositor.composite(canvas, layers)
        saved = await store.save_composite(result)
        return JSONResponse(
            content={
                "canvas_id": saved.canvas_id,
                "width": saved.width,
                "height": saved.height,
                "created_at": saved.created_at.isoformat(),
            }
        )

    @router.get("/{canvas_id}/composite/latest")
    async def latest_composite(
        canvas_id: str,
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        canvas = await store.get_canvas(canvas_id)
        if canvas is None or canvas.org_id != auth.org_id:
            raise HTTPException(status_code=404)
        comp = await store.latest_composite(canvas_id)
        if comp is None:
            raise HTTPException(status_code=404, detail="no composite exists yet")
        return JSONResponse(
            content={
                "canvas_id": comp.canvas_id,
                "width": comp.width,
                "height": comp.height,
                "created_at": comp.created_at.isoformat(),
            }
        )


def _register_export_routes(
    router: APIRouter,
    store: CanvasStore,
    executor: CanvasExecutor,
    compositor: CompositorService,
) -> None:
    # ── Export ─────────────────────────────────────────────────────────

    @router.get("/{canvas_id}/export")
    async def export_canvas(
        canvas_id: str,
        auth: CurrentUser = Depends(get_current_user),
        format: str = Query(default="png"),
        quality: int = Query(default=90),
    ) -> Response:
        canvas = await store.get_canvas(canvas_id)
        if canvas is None or canvas.org_id != auth.org_id:
            raise HTTPException(status_code=404)
        if canvas.is_archived():
            raise HTTPException(status_code=404)

        fmt = format.lower()
        if fmt not in _VALID_EXPORT_FORMATS:
            return _error(UnsupportedFormatError(f"unsupported format: {format!r}"))
        if not (1 <= quality <= 100):
            raise HTTPException(status_code=422, detail="quality must be between 1 and 100")

        return await _export_image(store, compositor, canvas, canvas_id, fmt, quality)

    # ── Models ─────────────────────────────────────────────────────────

    @router.get("/models")
    async def list_models(
        auth: CurrentUser = Depends(get_current_user),
    ) -> JSONResponse:
        # In production, this delegates to the model registry / LiteLLM;
        # the executor's model_registry exposes list_image_models() if available.
        if hasattr(executor, "_image_client") and hasattr(
            executor._image_client, "list_image_models"
        ):
            models = await executor._image_client.list_image_models()
            return JSONResponse(
                content=[
                    {
                        "id": m.id,
                        "display_name": m.display_name,
                        "provider": m.provider,
                        "supports_generate": m.supports_generate,
                        "supports_refine": m.supports_refine,
                        "tier_class": m.tier_class,
                        "cost_per_image_usd": m.cost_per_image_usd,
                        "is_free": m.is_free,
                    }
                    for m in models
                ]
            )
        return JSONResponse(content=[])
