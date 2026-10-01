"""Canvas API — /v2/canvas routes proxying the canvas ability (SPEC-070226-8239 Phase 1).

Implements ADR-045 Phase 1: maistro-server exposes ``/v2/canvas/*`` as the
canonical HTTP boundary for Canvas Studio, wrapping the canvas ability's
``CanvasStore`` / ``CompositorService``. The legacy routes in
``maistro_canvas.canvas.routes`` remain untouched and keep working in parallel.

Publish/export (M3-B4, #94) is a **governed** capability on this boundary:
``POST /designs/{id}/publish`` and ``GET /designs/{id}/export/{format}`` cross
the Capability -> Provider -> Binding -> Invocation seam via the injected
``app.state.canvas_exporter`` (a
``maistro_canvas.canvas.publishing.GovernedCanvasExporter`` or equivalent).
Routes never call a compositor/export provider directly. Each successful call
appends an immutable ``ExportVersion`` — a canonical artifact version with
provenance to the exact accepted canvas state, the producing Invocation, and
the Workspace/Project Binding — so re-export after an edit creates a new
version instead of overwriting history. Unconfigured governance is reported
truthfully (501); unsupported formats (pdf/svg) are refused with a
machine-readable 422, never simulated.

Dependency injection follows the existing maistro-server convention of app
state:

- ``app.state.canvas_store`` — required; an object satisfying the
  ``maistro_canvas.protocols.CanvasStore`` protocol (duck-typed here so
  maistro-server carries no hard dependency on maistro-canvas). If unset,
  every route returns 503.
- ``app.state.canvas_exporter`` — optional; the governed export façade.
  Publish/export return 501 when absent rather than degrading to direct
  provider calls.
- ``app.state.canvas_exports`` — optional; an ``ExportStore`` for listing and
  re-downloading historical export versions. Falls back to
  ``canvas_exporter.export_store`` when unset.
- ``app.state.canvas_compositor`` — optional; used only to acquire/refresh
  the pinned composite pixels underneath the governed export, never as the
  export path itself.
- ``app.state.canvas_events`` — optional; a (sync or async) callable
  ``(event: str, payload: dict) -> None``. maistro-server has no in-process
  event bus today, so mutation events (design.created / design.updated /
  design.deleted / design.exported / design.published) are emitted through
  this injected callable when wired (e.g. to the reactor bus per ADR-086) and
  are a no-op otherwise.
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

from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

router = APIRouter(prefix="/v2/canvas", tags=["canvas"])

# ── Content negotiation (ADR-076) ────────────────────────────────────

CANVAS_MEDIA_TYPE = "application/vnd.canvas+json"
_SUPPORTED_VERSION = "2"
_API_VERSION_HEADER = "Maistro-API-Version"

# Asset kinds per ADR-039 §1 (mirrors maistro_canvas.layers.LayerKind).
_ASSET_KINDS = ("background", "structure", "vehicle", "prop", "character", "fx", "text")


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
    # Scoped read (#857): the org rides into the SQL predicate, so another
    # org's canvas reads as absent rather than as a filtered row.
    record = await store.get_canvas(design_id, org_id=org_id)
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
        for layer in await store.list_layers(design_id, org_id=_owner_id(auth))
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
    updated = await store.update_canvas(record, org_id=_owner_id(auth))
    await _emit(request, "design.updated", {"design_id": design_id, "org_id": record.org_id})
    return _json(request, _design_dict(updated))


@router.delete("/designs/{design_id}")
async def delete_design(request: Request, design_id: str, auth: RequireAuth) -> JSONResponse:
    """Soft-delete: mark the canvas ability's ``archived_at``; no hard delete."""
    from datetime import UTC, datetime

    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))
    record.archived_at = datetime.now(UTC)
    await store.update_canvas(record, org_id=_owner_id(auth))
    await _emit(request, "design.deleted", {"design_id": design_id, "org_id": record.org_id})
    return _json(request, {"deleted": True, "id": design_id})


# ── Publish / export (governed, M3-B4 #94) ───────────────────────────


class PublishDesignRequest(BaseModel):
    """Publish one accepted canvas state as a canonical deliverable version.

    Publishing here records a governed export + provenance; outbound external
    destinations (print-on-demand, stores, media platforms) remain separate
    governed connectors that must consume accepted versions (#773) and are
    deliberately not implied by this call.
    """

    format: str = Field(default="png", pattern="^[a-z0-9_]+$")
    quality: int = Field(default=90, ge=1, le=100)
    design_project_id: str = Field(default="", max_length=200)


def _exporter(request: Request) -> Any:
    exporter = getattr(request.app.state, "canvas_exporter", None)
    if exporter is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Publish/export is not available: no governed export capability "
            "is configured (app.state.canvas_exporter missing). The engine will "
            "not fall back to a direct, ungoverned compositor call.",
        )
    return exporter


def _validate_format(exporter: Any, fmt: str) -> None:
    """Refuse deliberately-unsupported formats before any compositing work.

    When the wired exporter declares its supported formats (the shipped
    ``GovernedCanvasExporter`` does), a format outside the contract is a 422
    with a machine-readable code — a narrowed claim, never a simulated one.
    """
    declared = getattr(exporter, "supported_formats", None)
    if declared is None:
        return
    formats = declared() if callable(declared) else declared
    if fmt not in formats:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EXPORT_FORMAT_UNSUPPORTED",
                "reason": f"Export format {fmt!r} is not supported; supported "
                f"formats: {sorted(formats)}.",
            },
        )


def _export_store(request: Request) -> Any:
    store = getattr(request.app.state, "canvas_exports", None)
    if store is not None:
        return store
    exporter = _exporter(request)
    store = getattr(exporter, "export_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Export history is not available: no export store is configured "
            "(app.state.canvas_exports missing and the exporter exposes none).",
        )
    return store


async def _pinned_composite(request: Request, store: Any, design_id: str, org_id: str) -> Any:
    """Acquire the composite that pins the exact exported pixels.

    A stored composite is reused as-is; without one the configured compositor
    produces it now (and is cached back when the store supports caching, so a
    later export of the same state re-uses the same pixels). A compositor
    failure propagates as a truthful 502 — a configured provider failing is
    never converted into fake success.
    """
    composite = await store.latest_composite(design_id)
    if composite is None:
        compositor = getattr(request.app.state, "canvas_compositor", None)
        if compositor is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Export is not available: no composite exists and no compositor "
                "is configured (app.state.canvas_compositor missing).",
            )
        try:
            composite = await compositor.composite(
                await _require_design(store, design_id, org_id),
                await store.list_layers(design_id),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Composite failed: {exc}",
            ) from exc
        save = getattr(store, "save_composite", None)
        if callable(save):
            try:
                await save(composite)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Composite persistence failed: {exc}",
                ) from exc
    return composite


def _map_export_error(exc: Exception) -> HTTPException:
    """Map governed-export domain errors onto truthful HTTP failures.

    maistro-server carries no maistro-canvas dependency, so capability-domain
    errors are recognized by their stable ``code``/attribute surface rather
    than imported classes. Everything unrecognized is a downstream failure
    (502) — never masked as success.
    """
    if isinstance(exc, (InvocationDenied, InvocationApprovalRequired)):
        return HTTPException(status_code=403, detail=str(exc))
    code = getattr(exc, "code", None)
    if code == "EXPORT_FORMAT_UNSUPPORTED":
        return HTTPException(status_code=422, detail={"code": code, "reason": str(exc)})
    if code == "EXPORTER_DEPENDENCY_MISSING":
        return HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={"code": code, "reason": str(exc)},
        )
    invocation_id = getattr(exc, "invocation_id", None)
    if invocation_id is not None:
        # An ExportFailed-shaped error: the governed Invocation settled
        # non-completed. Surface the invocation identity for audit.
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": code or "EXPORT_FAILED",
                "reason": str(exc),
                "invocation_id": invocation_id,
                "invocation_status": getattr(exc, "invocation_status", "unknown"),
            },
        )
    return HTTPException(status_code=502, detail=f"Export failed: {exc}")


@router.post("/designs/{design_id}/publish")
async def publish_design(
    request: Request, design_id: str, body: PublishDesignRequest, auth: RequireAuth
) -> JSONResponse:
    """Publish one accepted design state as a governed deliverable version.

    Crosses the governed Binding/Invocation boundary: the export runs as a
    capability Invocation under the caller's Binding, and the produced
    artifact version is append-only with provenance to the exact accepted
    state, the producing Invocation, and the DesignProject when supplied.
    """
    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))
    exporter = _exporter(request)
    _validate_format(exporter, body.format)
    composite = await _pinned_composite(request, store, design_id, _owner_id(auth))
    layers = await store.list_layers(design_id)
    try:
        version = await exporter.export_canvas(
            record,
            layers,
            composite,
            fmt=body.format,
            quality=body.quality,
            actor_principal_id=_owner_id(auth),
            published=True,
            design_project_id=body.design_project_id,
        )
    except Exception as exc:
        raise _map_export_error(exc) from exc
    await _emit(
        request,
        "design.published",
        {
            "design_id": design_id,
            "org_id": record.org_id,
            "export_id": version.export_id,
            "format": version.format,
            "invocation_id": version.invocation_id,
            "state_digest": version.state_digest,
        },
    )
    response = dict(version.to_dict())
    response["download_url"] = f"/v2/canvas/designs/{design_id}/exports/{version.export_id}"
    return _json(request, response)


@router.get("/designs/{design_id}/export/{format}")
async def export_design(
    request: Request, design_id: str, format: str, auth: RequireAuth
) -> Response:
    """Export via the governed design.export capability (png/webp/jpg/jpeg/html/pptx).

    pdf/svg are refused with a machine-readable 422: they are deliberately out
    of scope, not temporarily unavailable. Response headers carry the export
    provenance (version id, Invocation id, state digest) so a downloaded file
    is traceable to the exact accepted state and governed Invocation.
    """
    store = _store(request)
    record = await _require_design(store, design_id, _owner_id(auth))
    exporter = _exporter(request)
    fmt = format.lower()
    _validate_format(exporter, fmt)
    composite = await _pinned_composite(request, store, design_id, _owner_id(auth))
    layers = await store.list_layers(design_id)
    try:
        version = await exporter.export_canvas(
            record,
            layers,
            composite,
            fmt=fmt,
            actor_principal_id=_owner_id(auth),
        )
    except Exception as exc:
        raise _map_export_error(exc) from exc
    await _emit(
        request,
        "design.exported",
        {
            "design_id": design_id,
            "org_id": record.org_id,
            "export_id": version.export_id,
            "format": version.format,
            "invocation_id": version.invocation_id,
        },
    )
    filename = f"design-{design_id[:8]}-{version.export_id[:8]}.{version.format}"
    return Response(
        content=version.content,
        media_type=version.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            _API_VERSION_HEADER: _SUPPORTED_VERSION,
            "X-Maistro-Export-Id": version.export_id,
            "X-Maistro-Invocation-Id": version.invocation_id,
            "X-Maistro-State-Digest": version.state_digest,
        },
    )


@router.get("/designs/{design_id}/exports")
async def list_design_exports(request: Request, design_id: str, auth: RequireAuth) -> JSONResponse:
    """List every exported artifact version of this design (append-only history)."""
    store = _store(request)
    await _require_design(store, design_id, _owner_id(auth))
    exports = _export_store(request)
    versions = await exports.list_for_canvas(design_id, org_id=_owner_id(auth))
    return _json(request, [v.to_dict() for v in versions])


@router.get("/designs/{design_id}/exports/{export_id}")
async def get_design_export(
    request: Request, design_id: str, export_id: str, auth: RequireAuth
) -> Response:
    """Re-download one historical export version — the exact historical bytes.

    Historical versions are immutable: a later edit never overwrites them,
    which is what keeps provenance between preview, acceptance, and export.
    """
    store = _store(request)
    await _require_design(store, design_id, _owner_id(auth))
    exports = _export_store(request)
    version = await exports.get(design_id, export_id, org_id=_owner_id(auth))
    if version is None:
        raise HTTPException(status_code=404, detail="Export version not found")
    filename = f"design-{design_id[:8]}-{version.export_id[:8]}.{version.format}"
    return Response(
        content=version.content,
        media_type=version.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            _API_VERSION_HEADER: _SUPPORTED_VERSION,
            "X-Maistro-Export-Id": version.export_id,
            "X-Maistro-Invocation-Id": version.invocation_id,
            "X-Maistro-State-Digest": version.state_digest,
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


# The handlers are this module's public surface: FastAPI registers them from
# the decorators, which static import scanning cannot see. Declaring them here
# is the same statement a2a.py's __all__ makes (see the comment there), and is
# what keeps this module's route handlers out of the fastapi-route-handler
# Vulture ledger: a new handler must join this list (the drift is caught by
# test_canvas_all_covers_every_route_handler), not silently re-enter the
# dead-code ratchet as unbanked debt.
__all__ = [
    "create_design",
    "delete_design",
    "export_design",
    "get_design",
    "get_design_export",
    "list_assets",
    "list_design_exports",
    "list_designs",
    "publish_design",
    "router",
    "update_design",
]
