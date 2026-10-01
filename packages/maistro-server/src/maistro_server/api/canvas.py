"""Canvas API — /v2/canvas routes proxying the canvas ability (SPEC-070226-8239 Phase 1).

Implements ADR-045 Phase 1: maistro-server exposes ``/v2/canvas/*`` as the
canonical HTTP boundary for Canvas Studio, wrapping the canvas ability's
``CanvasStore`` / ``CompositorService``. The legacy routes in
``maistro_canvas.canvas.routes`` remain untouched and keep working in parallel.

Dependency injection follows the existing maistro-server convention of app
state:

- ``app.state.canvas_store`` — required; an object satisfying the
  ``maistro_canvas.protocols.CanvasStore`` protocol (duck-typed here so
  maistro-server carries no hard dependency on maistro-canvas). If unset,
  every route returns 503.
- ``app.state.canvas_compositor`` — optional; a ``CompositorService``. When
  absent, export returns 501.
- ``app.state.canvas_events`` — optional; a (sync or async) callable
  ``(event: str, payload: dict) -> None``. maistro-server has no in-process
  event bus today, so mutation events (design.created / design.updated /
  design.deleted) are emitted through this injected callable when wired
  (e.g. to the reactor bus per ADR-086) and are a no-op otherwise.
- ``app.state.canvas_asset_registry`` — optional; an ``AssetRegistry``
  (``list_by_kind``). Backs GET /v2/canvas/assets; 501 when absent.

Content negotiation (ADR-076, minimal mechanism): requests may send
``Accept: application/vnd.canvas+json;version=2`` and receive the same body
with that content type; plain ``application/json`` is the default. Unknown
requested versions get 406.

A "design" in the /v2 surface is a canvas ability ``CanvasRecord``;
soft-delete maps to the record's ``archived_at`` marker (the ability's own
soft-delete), after which GET returns 404.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

router = APIRouter(prefix="/v2/canvas", tags=["canvas"])

# ── Content negotiation (ADR-076) ────────────────────────────────────

CANVAS_MEDIA_TYPE = "application/vnd.canvas+json"
_SUPPORTED_VERSION = "2"
_API_VERSION_HEADER = "Maistro-API-Version"

# Asset kinds per ADR-039 §1 (mirrors maistro_canvas.layers.LayerKind).
_ASSET_KINDS = ("background", "structure", "vehicle", "prop", "character", "fx", "text")

_EXPORT_MEDIA_TYPES: dict[str, str] = {
    "png": "image/png",
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def _negotiated_media_type(request: Request) -> str:
    """Resolve the response media type from the Accept header.

    ``application/vnd.canvas+json`` (optionally with ``;version=2``) selects
    the versioned media type; anything else falls back to application/json.
    An explicit unsupported version is a 406.
    """
    accept = request.headers.get("accept", "")
    for raw_part in accept.split(","):
        part = raw_part.strip()
        if not part.startswith(CANVAS_MEDIA_TYPE):
            continue
        version = _SUPPORTED_VERSION
        for param in part.split(";")[1:]:
            key, _, value = param.strip().partition("=")
            if key.strip() == "version":
                version = value.strip()
        if version != _SUPPORTED_VERSION:
            raise HTTPException(
                status_code=status.HTTP_406_NOT_ACCEPTABLE,
                detail=f"Unsupported canvas API version {version!r}; supported: 2",
            )
        return f"{CANVAS_MEDIA_TYPE};version={_SUPPORTED_VERSION}"
    return "application/json"


def _json(request: Request, content: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=content,
        status_code=status_code,
        media_type=_negotiated_media_type(request),
        headers={_API_VERSION_HEADER: _SUPPORTED_VERSION},
    )


# ── Duck-typed views of the canvas ability (no maistro-canvas import) ─


@runtime_checkable
class _DesignRecord(Protocol):
    """Structural subset of maistro_canvas.types.CanvasRecord used here."""

    id: str
    org_id: str
    name: str
    width: int
    height: int
    background_color: str
    archived_at: Any

    def to_dict(self) -> dict[str, Any]: ...


def _store(request: Request) -> Any:
    store = getattr(request.app.state, "canvas_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canvas ability is not configured (app.state.canvas_store missing)",
        )
    return store


async def _emit(request: Request, event: str, payload: dict[str, Any]) -> None:
    """Emit a canvas event via the injected callable, if any (see module docstring)."""
    emit = getattr(request.app.state, "canvas_events", None)
    if emit is None:
        return
    result = emit(event, payload)
    if inspect.isawaitable(result):
        await result


def _owner_id(auth: AuthenticatedPrincipal | None) -> str:
    return "dev" if auth is None else auth.user_id


async def _require_design(store: Any, design_id: str, org_id: str) -> _DesignRecord:
    record = await store.get_canvas(design_id)
    if (
        record is None
        or record.org_id != org_id
        or getattr(record, "archived_at", None) is not None
    ):
        raise HTTPException(status_code=404, detail="Design not found")
    return record  # type: ignore[no-any-return]


def _design_dict(record: _DesignRecord) -> dict[str, Any]:
    return record.to_dict()


# ── Request bodies ────────────────────────────────────────────────────


class CreateDesignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    background_color: str = "#FFFFFF"


class UpdateDesignRequest(BaseModel):
    """PATCH semantics: omitted fields are unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    background_color: str | None = None


# ── Design CRUD ───────────────────────────────────────────────────────


@router.get("/designs")
async def list_designs(request: Request, auth: RequireAuth) -> JSONResponse:
    store = _store(request)
    records = await store.list_canvases(_owner_id(auth))
    return _json(request, [_design_dict(r) for r in records])


@router.post("/designs", status_code=status.HTTP_201_CREATED)
async def create_design(
    request: Request, body: CreateDesignRequest, auth: RequireAuth
) -> JSONResponse:
    store = _store(request)
    try:
        record = await store.create_canvas(
            name=body.name,
            width=body.width,
            height=body.height,
            background_color=body.background_color,
            org_id=_owner_id(auth),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _emit(request, "design.created", {"design_id": record.id, "org_id": record.org_id})
    return _json(request, _design_dict(record), status_code=status.HTTP_201_CREATED)


@router.get("/designs/{design_id}")
async def get_design(request: Request, design_id: str, auth: RequireAuth) -> JSONResponse:
    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))
    body = _design_dict(record)
    body["layers"] = [
        layer.to_dict() if hasattr(layer, "to_dict") else asdict(layer)
        for layer in await store.list_layers(design_id)
        if hasattr(layer, "to_dict") or is_dataclass(layer)
    ]
    return _json(request, body)


@router.put("/designs/{design_id}")
async def update_design(
    request: Request, design_id: str, body: UpdateDesignRequest, auth: RequireAuth
) -> JSONResponse:
    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))
    if body.name is not None:
        record.name = body.name
    if body.background_color is not None:
        record.background_color = body.background_color
    updated = await store.update_canvas(record)
    await _emit(request, "design.updated", {"design_id": design_id, "org_id": record.org_id})
    return _json(request, _design_dict(updated))


@router.delete("/designs/{design_id}")
async def delete_design(request: Request, design_id: str, auth: RequireAuth) -> JSONResponse:
    """Soft-delete: mark the canvas ability's ``archived_at``; no hard delete."""
    from datetime import UTC, datetime

    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))
    record.archived_at = datetime.now(UTC)
    await store.update_canvas(record)
    await _emit(request, "design.deleted", {"design_id": design_id, "org_id": record.org_id})
    return _json(request, {"deleted": True, "id": design_id})


# ── Publish / export ─────────────────────────────────────────────────


@router.post("/designs/{design_id}/publish")
async def publish_design(request: Request, design_id: str, auth: RequireAuth) -> JSONResponse:
    """501 stub: the canvas ability exposes no publish operation.

    Print-on-demand (Lulu) lives in the Canvas Studio frontend server, outside
    the engine. Wire this when a publish capability lands in maistro-canvas.
    """
    store = _store(request)
    await _require_design(store, design_id, _owner_id(auth))
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Publish is not implemented: the canvas ability exposes no publish "
        "operation (print-on-demand integration lives in Canvas Studio).",
    )


@router.get("/designs/{design_id}/export/{format}")
async def export_design(
    request: Request, design_id: str, format: str, auth: RequireAuth
) -> Response:
    """Export via the canvas compositor (png/webp/jpg). pdf/svg are 501."""
    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))

    fmt = format.lower()
    if fmt not in _EXPORT_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Export format {format!r} is not implemented: the canvas "
            f"compositor encodes only {sorted(set(_EXPORT_MEDIA_TYPES))}.",
        )

    compositor = getattr(request.app.state, "canvas_compositor", None)
    if compositor is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Export is not available: no compositor is configured "
            "(app.state.canvas_compositor missing).",
        )

    composite = await store.latest_composite(design_id)
    if composite is None:
        layers = await store.list_layers(design_id)
        composite = await compositor.composite(record, layers)
        await store.save_composite(composite)

    output: bytes = composite.image_bytes
    if fmt != "png" and hasattr(compositor, "encode"):
        output = await compositor.encode(composite.image_bytes, fmt=fmt, quality=90)

    return Response(
        content=output,
        media_type=_EXPORT_MEDIA_TYPES[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="design-{design_id[:8]}.{fmt}"',
            _API_VERSION_HEADER: _SUPPORTED_VERSION,
        },
    )


# ── Assets ────────────────────────────────────────────────────────────


@router.get("/assets")
async def list_assets(request: Request, auth: RequireAuth, kind: str | None = None) -> JSONResponse:
    """List registered asset definitions via the injected AssetRegistry.

    Optional ``kind`` filters by ADR-039 layer kind; otherwise all kinds are
    aggregated. 501 when no registry is wired.
    """
    _ = auth
    registry = getattr(request.app.state, "canvas_asset_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Asset listing is not available: no asset registry is configured "
            "(app.state.canvas_asset_registry missing).",
        )
    kinds = (kind,) if kind else _ASSET_KINDS
    assets: list[dict[str, Any]] = []
    for k in kinds:
        for definition in await registry.list_by_kind(k):
            if is_dataclass(definition) and not isinstance(definition, type):
                assets.append(asdict(definition))
            else:
                assets.append(dict(definition))
    return _json(request, assets)
