"""Governed Design Studio publish/export for Canvas-backed artifacts (M3-B4, #94).

Canvas owns the visual export capability; the product surface (maistro-server
``/v2/canvas``) must cross the governed Capability -> Provider -> Binding ->
Invocation boundary rather than calling a compositor directly (ADR-045:
"External effects such as publish/export remain governed capabilities").

What this module provides:

- :class:`DesignExportProvider` — the ``design.export`` capability provider.
  It turns one pinned canvas state into PNG/WEBP/JPG bytes (via the injected
  compositor) or HTML (plugin-free fixed-page serialization). PPTX works when
  ``python-pptx`` is installed and fails truthfully with
  :class:`~maistro_canvas.export.ExporterDependencyError` when it is not.
  PDF/SVG are deliberately **unsupported** and rejected with
  :class:`ExportFormatUnsupported` — a narrowed claim, not a fake success.

- :func:`canvas_state_digest` — the immutable "accepted state" pin. Export
  effect identity and the produced artifact version are keyed to this digest,
  so the exact version a user accepted is the exact version exported: any
  later edit produces a new digest, a new effect key, a new Invocation, and a
  new append-only :class:`ExportVersion` instead of overwriting history.

- :class:`GovernedCanvasExporter` — the façade products call. Every export is
  one governed Invocation (policy decision, durable Invocation row with a
  :class:`~maistro.capabilities.binding.ResolvedBinding` snapshot, truthful
  FAILED/UNKNOWN terminal states) under canonical ``Run -> NodeRun -> Attempt``
  identity when a run spine is wired, or request-scoped identity otherwise.

Failures are truthful: a compositor/encoder error surfaces as a FAILED or
UNKNOWN Invocation plus :class:`ExportFailed` — never as synthesized bytes.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.governed_invocation import (
    GovernedInvocationExecutionService,
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.invocation import (
    EffectNotApplied,
    Invocation,
    InvocationExecutionService,
    InvocationStatus,
    ProviderResolver,
)
from maistro.capabilities.types import ProviderHealth
from maistro_canvas.export import ExportLayer, ExportPage, ExportText, export_html, export_pptx
from maistro_canvas.types import CanvasError, CanvasRecord, CompositeResult, LayerRecord

#: Formats the export provider can genuinely produce in this repository.
#: ``jpeg`` is a legacy alias of ``jpg`` kept for compatibility with the
#: pre-governance route (same JPEG encoder, same ``image/jpeg`` media type).
IMAGE_FORMATS = ("png", "webp", "jpg", "jpeg")
#: Media types for the image formats, shared with the HTTP boundary.
IMAGE_MEDIA_TYPES: dict[str, str] = {
    "png": "image/png",
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
#: Fixed-page HTML serialization is stdlib-only and always available.
HTML_FORMAT = "html"
#: Deck format with an optional dependency (python-pptx). Requesting it when
#: the dependency is absent raises ``ExporterDependencyError`` truthfully.
PPTX_FORMAT = "pptx"
#: Deliberately unsupported formats. The provider rejects them with a
#: machine-readable error listing what *is* supported.
UNSUPPORTED_FORMATS = ("pdf", "svg")

SUPPORTED_EXPORT_FORMATS = (*IMAGE_FORMATS, HTML_FORMAT, PPTX_FORMAT)

_SLOT = "design.export"


# ── Domain errors ────────────────────────────────────────────────────────


class ExportError(CanvasError):
    code = "EXPORT_ERROR"


class ExportFormatUnsupported(ExportError):
    """A format deliberately outside the supported export contract."""

    code = "EXPORT_FORMAT_UNSUPPORTED"

    def __init__(self, fmt: str) -> None:
        super().__init__(
            f"Export format {fmt!r} is not supported; supported formats: "
            f"{list(SUPPORTED_EXPORT_FORMATS)} (pdf/svg are out of scope and "
            "are not claimed as deliverables)."
        )


class ExportFailed(ExportError):
    """The governed export Invocation did not complete (truthful failure)."""

    code = "EXPORT_FAILED"

    def __init__(self, message: str, *, invocation_id: str, status: str) -> None:
        super().__init__(message)
        self.invocation_id = invocation_id
        self.invocation_status = status


class ExportVersionExistsError(ExportError):
    """Append-only violation: an export version id was reused."""

    code = "EXPORT_VERSION_EXISTS"


# ── State pinning ────────────────────────────────────────────────────────


def canvas_state_digest(canvas: CanvasRecord, layers: list[LayerRecord]) -> str:
    """Digest the exact accepted canvas state: record + ordered layer snapshots.

    Two exports of the same accepted state share a digest, so re-export is
    idempotent; any edit (position, text, tier, visibility, ordering) changes
    the digest, which is what prevents preview/export drift and creates
    a fresh artifact version after a later manual or AI edit.

    Volatile audit timestamps (``created_at``/``updated_at``/``archived_at``)
    are deliberately excluded: they change on any write, including non-visual
    ones, and would silently fork export versions without a real edit.
    """

    def _pin(record: Any, fields: tuple[str, ...]) -> list[Any]:
        return [getattr(record, name) for name in fields]

    canvas_fields = (
        "id",
        "name",
        "width",
        "height",
        "background_color",
        "org_id",
    )
    layer_fields = (
        "id",
        "canvas_id",
        "name",
        "layer_type",
        "z_index",
        "x",
        "y",
        "scale",
        "rotation",
        "opacity",
        "blend_mode",
        "visible",
        "locked",
        "image_path",
        "prompt",
        "negative_prompt",
        "model_id",
        "tier",
        "generation_seed",
        "text_config",
    )
    payload = {
        "canvas": _pin(canvas, canvas_fields),
        "layers": [
            _pin(layer, layer_fields)
            for layer in sorted(layers, key=lambda layer: (layer.z_index, layer.id))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Invocation request/result payloads ───────────────────────────────────


class ExportRequest(BaseModel):
    """The governed Invocation request. Digest-stable for approvals/dedup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canvas_id: str
    format: str
    quality: int = 90
    state_digest: str
    composite_digest: str = ""


class ExportResult(BaseModel):
    """The physical export bytes plus the pins they were produced from."""

    model_config = ConfigDict(frozen=True)

    format: str
    media_type: str
    content: bytes
    state_digest: str
    composite_digest: str
    width: int
    height: int

    @property
    def sha256(self) -> str:
        return _sha256(self.content)

    @property
    def byte_size(self) -> int:
        return len(self.content)


# ── Provider ─────────────────────────────────────────────────────────────


class DesignExportProvider:
    """``design.export`` capability provider over the Canvas compositor/serializers.

    Never called directly by product code — resolved through a Binding by the
    governed invocation service, so the provider choice is persisted on every
    Invocation as a ``ResolvedBinding`` snapshot.
    """

    def __init__(self, compositor: Any) -> None:
        self._compositor = compositor

    @property
    def name(self) -> str:
        return "canvas-fixed-page-exporter"

    @property
    def slot(self) -> str:
        return _SLOT

    @property
    def trust_tier(self) -> str:
        return "t0"  # engine-shipped, immutable

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, detail="in-process canvas export provider")

    async def export(
        self,
        request: ExportRequest,
        canvas: CanvasRecord,
        layers: list[LayerRecord],
        composite: CompositeResult,
    ) -> ExportResult:
        """Produce the export bytes for one pinned state, or raise truthfully."""
        fmt = request.format
        if fmt in UNSUPPORTED_FORMATS or fmt not in SUPPORTED_EXPORT_FORMATS:
            raise ExportFormatUnsupported(fmt)

        composite_digest = _sha256(composite.image_bytes)
        base = {
            "state_digest": request.state_digest,
            "composite_digest": composite_digest,
            "width": canvas.width,
            "height": canvas.height,
        }

        if fmt in IMAGE_FORMATS:
            content = await self._encode_image(composite.image_bytes, fmt, request.quality)
            return ExportResult(
                format=fmt, media_type=IMAGE_MEDIA_TYPES[fmt], content=content, **base
            )
        page = _page_from(canvas, layers, composite.image_bytes)
        if fmt == HTML_FORMAT:
            return ExportResult(
                format=HTML_FORMAT,
                media_type="text/html; charset=utf-8",
                content=export_html(page).encode("utf-8"),
                **base,
            )
        # PPTX: lazily imports python-pptx; ExporterDependencyError propagates
        # when the optional dependency is absent (truthful unavailability).
        return ExportResult(
            format=PPTX_FORMAT,
            media_type=(
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
            content=export_pptx([page]),
            **base,
        )

    async def _encode_image(self, png_bytes: bytes, fmt: str, quality: int) -> bytes:
        if fmt == "png":
            return png_bytes
        encode = getattr(self._compositor, "encode", None)
        if encode is None:
            raise EffectNotApplied(
                f"format {fmt!r} requires a compositor with an encode() backend; "
                "the configured compositor produces PNG only"
            )
        encoded: bytes = await encode(png_bytes, fmt=fmt, quality=quality)
        return encoded


def _page_from(canvas: CanvasRecord, layers: list[LayerRecord], composite_png: bytes) -> ExportPage:
    """Map canvas records onto the fixed-page export model.

    Image layers carry the composite PNG (the exact composited pixels of the
    pinned state); text layers stay real text so HTML/PPTX output remains
    editable rather than rasterized.
    """
    image_layers = [
        ExportLayer(
            z_index=lyr.z_index,
            x=lyr.x,
            y=lyr.y,
            rotation=lyr.rotation,
            opacity=lyr.opacity,
            image_png=composite_png,  # pinned composite pixels, HTML data-uri + PPTX picture
        )
        for lyr in layers
        if lyr.visible and lyr.image_path
    ]
    text_layers = [
        ExportLayer(
            z_index=lyr.z_index,
            x=lyr.x,
            y=lyr.y,
            rotation=lyr.rotation,
            opacity=lyr.opacity,
            text=ExportText(
                content=cfg.content,
                font=cfg.font,
                size=cfg.size,
                color=cfg.color,
                weight=cfg.weight,
                alignment=cfg.alignment,
            ),
        )
        for lyr in layers
        if lyr.visible and lyr.layer_type == "text" and (cfg := lyr.text_config) is not None
    ]
    return ExportPage(
        width=canvas.width,
        height=canvas.height,
        background_color=canvas.background_color,
        layers=[*image_layers, *text_layers],
    )


# ── Export versions (canonical artifacts) ────────────────────────────────


@dataclass(frozen=True)
class ExportVersion:
    """One immutable exported artifact version with full provenance.

    Append-only by contract: a re-export after a later edit is a *new* row;
    historical rows are never mutated or overwritten. ``run_id`` /
    ``node_run_id`` / ``attempt_id`` are the canonical execution identity the
    export ran under, ``invocation_id`` / ``binding_id`` tie the artifact to
    its governed Invocation and Binding. ``design_project_id`` records the
    owning DesignProject when the caller supplies it (Design Studio knows the
    project; Canvas stores the link without owning project state).
    """

    export_id: str
    canvas_id: str
    org_id: str
    format: str
    media_type: str
    byte_size: int
    sha256: str
    state_digest: str
    composite_digest: str
    width: int
    height: int
    run_id: str
    node_run_id: str
    attempt_id: str
    invocation_id: str
    binding_id: str
    published: bool = False
    design_project_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    content: bytes = b""

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {
            "export_id": self.export_id,
            "canvas_id": self.canvas_id,
            "org_id": self.org_id,
            "format": self.format,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "state_digest": self.state_digest,
            "composite_digest": self.composite_digest,
            "width": self.width,
            "height": self.height,
            "run_id": self.run_id,
            "node_run_id": self.node_run_id,
            "attempt_id": self.attempt_id,
            "invocation_id": self.invocation_id,
            "binding_id": self.binding_id,
            "published": self.published,
            "design_project_id": self.design_project_id,
            "created_at": self.created_at.isoformat(),
        }
        if include_content:
            body["content"] = self.content.decode("utf-8", errors="replace")
        return body


@runtime_checkable
class ExportStore(Protocol):
    """Durable persistence contract for exported artifact versions."""

    async def save(self, version: ExportVersion) -> ExportVersion: ...

    async def get(self, canvas_id: str, export_id: str, *, org_id: str) -> ExportVersion | None: ...

    async def list_for_canvas(self, canvas_id: str, *, org_id: str) -> list[ExportVersion]: ...

    async def find_by_invocation(self, invocation_id: str) -> ExportVersion | None: ...


class InMemoryExportStore:
    """Append-only in-memory ExportStore (tests / unwired local runs).

    Production composes a durable implementation via app.state in the same way
    ``canvas_store`` is injected; :class:`ExportStore` is the seam.
    """

    def __init__(self) -> None:
        self._versions: dict[str, ExportVersion] = {}

    async def save(self, version: ExportVersion) -> ExportVersion:
        if version.export_id in self._versions:
            raise ExportVersionExistsError(
                f"export version {version.export_id!r} already exists; "
                "export versions are append-only"
            )
        self._versions[version.export_id] = version
        return version

    async def get(self, canvas_id: str, export_id: str, *, org_id: str) -> ExportVersion | None:
        found = self._versions.get(export_id)
        if found is None or found.canvas_id != canvas_id or found.org_id != org_id:
            return None
        return found

    async def list_for_canvas(self, canvas_id: str, *, org_id: str) -> list[ExportVersion]:
        return [
            v for v in self._versions.values() if v.canvas_id == canvas_id and v.org_id == org_id
        ]

    async def find_by_invocation(self, invocation_id: str) -> ExportVersion | None:
        for version in self._versions.values():
            if version.invocation_id == invocation_id:
                return version
        return None


# ── Run spine (canonical Run -> NodeRun -> Attempt) ──────────────────────


@runtime_checkable
class ExportRunSpine(Protocol):
    """Admission + physical-execution recording on the canonical run spine.

    Implemented (in production wiring) by an adapter over
    ``maistro.runs.service.RunExecutionService`` bound to one authorized
    Workspace/Project, mirroring ``CanvasCanonicalExecution`` for generation
    jobs. Export never creates a competing lifecycle: it is one Run with a
    single ``design.export`` node whose Attempt carries the governed
    Invocation.
    """

    async def execute_export(
        self,
        *,
        canvas_id: str,
        actor_principal_id: str | None,
        executor: Callable[[str, str, str], Awaitable[tuple[Invocation, ExportResult]]],
    ) -> tuple[str, str, str]:
        """Run the export node; return (run_id, node_run_id, attempt_id).

        ``executor`` performs the governed Invocation under the ids the spine
        allocated and returns the terminal Invocation plus the physical
        export result; the spine records both on the Attempt.
        """


# ── Governed façade ──────────────────────────────────────────────────────


class GovernedCanvasExporter:
    """The only sanctioned way product code produces a Canvas export.

    Sequence per export: pin the accepted state (digest) -> resolve the
    composite for exactly that state -> one governed Invocation under the
    caller's Binding -> append-only :class:`ExportVersion` carrying full
    provenance. Same-state re-export replays the completed Invocation and
    returns the same version; a later edit (new state digest) creates a new
    version. Provider failures surface as FAILED/UNKNOWN Invocations plus
    :class:`ExportFailed` — never as fake bytes.
    """

    def __init__(
        self,
        *,
        provider: DesignExportProvider,
        invocation_service: GovernedInvocationExecutionService | InvocationExecutionService,
        export_store: ExportStore,
        binding: Binding,
        resolver: ProviderResolver,
        run_spine: ExportRunSpine | None = None,
    ) -> None:
        self._provider = provider
        self._invocations = invocation_service
        self._store = export_store
        self._binding = binding
        self._resolver = resolver
        self._run_spine = run_spine
        # Per-export canvas context so the slot-specific executor below can
        # reach the state this export pinned, without widening the generic
        # ProviderExecutor signature the invocation service uses.
        self._context: contextvars.ContextVar[
            tuple[CanvasRecord, list[LayerRecord], CompositeResult] | None
        ] = contextvars.ContextVar(f"canvas-export-context-{id(self)}", default=None)

    @property
    def binding(self) -> Binding:
        return self._binding

    @property
    def supported_formats(self) -> tuple[str, ...]:
        """Formats this exporter can genuinely produce (request-validation seam)."""
        return SUPPORTED_EXPORT_FORMATS

    @property
    def export_store(self) -> ExportStore:
        return self._store

    async def export_canvas(
        self,
        canvas: CanvasRecord,
        layers: list[LayerRecord],
        composite: CompositeResult,
        *,
        fmt: str,
        quality: int = 90,
        actor_principal_id: str | None = None,
        published: bool = False,
        design_project_id: str = "",
    ) -> ExportVersion:
        """Export one accepted canvas state through the governed boundary."""
        if fmt in UNSUPPORTED_FORMATS or fmt not in SUPPORTED_EXPORT_FORMATS:
            raise ExportFormatUnsupported(fmt)

        state_digest = canvas_state_digest(canvas, layers)
        request = ExportRequest(
            canvas_id=canvas.id,
            format=fmt,
            quality=quality,
            state_digest=state_digest,
            composite_digest=_sha256(composite.image_bytes),
        )
        effect_key = f"design-export:{canvas.id}:{fmt}:{state_digest}"
        self._context.set((canvas, layers, composite))

        # The terminal Invocation of this export, captured by dispatch(). With
        # a spine, the ids come from the canonical Attempt; the Invocation
        # object itself is still produced by the dispatch closure under them.
        terminal: list[Invocation] = []

        async def dispatch(
            run_id: str, node_run_id: str, attempt_id: str
        ) -> tuple[Invocation, ExportResult]:
            invocation = await self._invocations.invoke(
                binding=self._binding,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                effect_key=effect_key,
                request=request,
                resolver=self._resolver,
                executor=self._execute_with_provider,
            )
            terminal.append(invocation)
            return invocation, self._result_from(invocation)

        if self._run_spine is not None:
            run_id, node_run_id, attempt_id = await self._run_spine.execute_export(
                canvas_id=canvas.id,
                actor_principal_id=actor_principal_id,
                executor=dispatch,
            )
        else:
            # Request-scoped identity is deterministic per (org, canvas,
            # format, state): a same-state re-export resolves the same
            # canonical effect scope, so the invocation service's completed
            # effect replay makes it idempotent. An edit changes the state
            # digest and therefore the whole identity — a genuinely new
            # export, never a mutation of the old one.
            pin = f"{canvas.org_id}:{canvas.id}:{state_digest[:16]}"
            run_id = f"canvas-export:{pin}"
            node_run_id = f"canvas-export:{pin}:{fmt}"
            attempt_id = f"canvas-export-attempt:{uuid4().hex[:16]}"
            await dispatch(run_id, node_run_id, attempt_id)

        return await self._persist_version(
            canvas=canvas,
            fmt=fmt,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            invocation=terminal[-1] if terminal else None,
            published=published,
            design_project_id=design_project_id,
        )

    async def _execute_with_provider(
        self, provider: ResolvedCapabilityProvider, request: Any
    ) -> ExportResult:
        """Slot-specific ProviderExecutor: dispatch onto the resolved provider."""
        context = self._context.get()
        if context is None:
            raise EffectNotApplied("design.export executed without pinned canvas context")
        canvas, layers, composite = context
        export = getattr(provider, "export", None)
        if export is None:
            raise EffectNotApplied(
                f"resolved provider {provider.name!r} does not implement design.export"
            )
        exported: ExportResult = await export(request, canvas, layers, composite)
        return exported

    def _result_from(self, invocation: Invocation) -> ExportResult:
        result = invocation.result
        if invocation.status is not InvocationStatus.COMPLETED or not isinstance(
            result, ExportResult
        ):
            status = invocation.status.value
            error = invocation.error or "no export result recorded"
            raise ExportFailed(
                f"export invocation {invocation.invocation_id} ended {status}: {error}",
                invocation_id=invocation.invocation_id,
                status=status,
            )
        return result

    async def _persist_version(
        self,
        *,
        canvas: CanvasRecord,
        fmt: str,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        invocation: Invocation | None,
        published: bool,
        design_project_id: str,
    ) -> ExportVersion:
        invocation_id = invocation.invocation_id if invocation is not None else ""

        # Idempotent replay: the same accepted state maps to the same effect
        # key; return the existing version instead of appending a duplicate.
        if invocation_id:
            existing = await self._store.find_by_invocation(invocation_id)
            if existing is not None:
                return existing

        # The completed Invocation is the authority for the physical bytes.
        if invocation is None or invocation.status is not InvocationStatus.COMPLETED:
            raise ExportFailed(
                f"export invocation {invocation_id!r} is not completed",
                invocation_id=invocation_id,
                status=invocation.status.value if invocation is not None else "unknown",
            )
        result = invocation.result
        if not isinstance(result, ExportResult):  # pragma: no cover - defensive
            raise ExportFailed(
                f"export invocation {invocation_id!r} recorded no export result",
                invocation_id=invocation_id,
                status=invocation.status.value,
            )

        version = ExportVersion(
            export_id=uuid4().hex,
            canvas_id=canvas.id,
            org_id=canvas.org_id,
            format=result.format or fmt,
            media_type=result.media_type,
            byte_size=result.byte_size,
            sha256=result.sha256,
            state_digest=result.state_digest,
            composite_digest=result.composite_digest,
            width=result.width,
            height=result.height,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            invocation_id=invocation.invocation_id,
            binding_id=self._binding.binding_id,
            published=published,
            design_project_id=design_project_id,
            content=result.content,
        )
        return await self._store.save(version)


# Re-exported so the HTTP boundary can map governed refusals without importing
# capability internals from multiple modules.
GOVERNED_REFUSALS = (InvocationDenied, InvocationApprovalRequired)


def export_media_type(fmt: str) -> str:
    """Media type for a supported export format; empty string when unsupported."""
    if fmt in IMAGE_MEDIA_TYPES:
        return IMAGE_MEDIA_TYPES[fmt]
    if fmt == HTML_FORMAT:
        return "text/html; charset=utf-8"
    if fmt == PPTX_FORMAT:
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return ""


__all__ = [
    "GOVERNED_REFUSALS",
    "HTML_FORMAT",
    "IMAGE_FORMATS",
    "PPTX_FORMAT",
    "SUPPORTED_EXPORT_FORMATS",
    "UNSUPPORTED_FORMATS",
    "DesignExportProvider",
    "ExportError",
    "ExportFailed",
    "ExportFormatUnsupported",
    "ExportRequest",
    "ExportResult",
    "ExportRunSpine",
    "ExportStore",
    "ExportVersion",
    "ExportVersionExistsError",
    "GovernedCanvasExporter",
    "InMemoryExportStore",
    "canvas_state_digest",
    "export_media_type",
]
