"""Canvas Studio types: enums, dataclasses, and domain errors.

All runtime data flows through these types. The persistence layer
serialises/deserialises to/from storage; the API layer serialises
to/from JSON. Neither layer is imported here.

POC additions (book-maker-poc branch):
  - BookLayer: per-page layer with version history[], retry() + upgrade()
    methods enforcing version_history_never_loses_images invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# maistro-core ships no py.typed marker yet, so its modules are untyped here.
from maistro.types.errors import AgentError

# ─────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────


class LayerType(StrEnum):
    BACKGROUND = "background"
    CHARACTER = "character"
    OBJECT = "object"
    TEXT = "text"


class BlendMode(StrEnum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    DARKEN = "darken"
    LIGHTEN = "lighten"


class JobAction(StrEnum):
    GENERATE = "generate"
    REFINE = "refine"
    REFERENCE = "reference"
    COMPOSITE = "composite"
    TEXT = "text"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CanvasTier(StrEnum):
    DRAFT = "draft"
    PROOF = "proof"


_IMAGE_GEN_ACTIONS = frozenset({JobAction.GENERATE, JobAction.REFINE, JobAction.REFERENCE})

# ─────────────────────────────────────────────────────────────────────
# POC addition: per-page layer with version history
# ─────────────────────────────────────────────────────────────────────


@dataclass
class BookLayer:
    """Per-page layer with version history.

    Enforces the SPEC invariant version_history_never_loses_images:
    old image_url is always pushed to history[] before replacement.
    """

    name: str
    layer_type: str  # 'background' | 'character' | 'prop' | 'text'
    image_url: str | None = None
    prompt: str | None = None
    z_index: int = 0
    visible: bool = True
    quality: str = "draft"  # 'draft' | 'final'
    history: list[str] = field(default_factory=list)
    slot: dict[str, Any] | str | None = None
    pose: dict[str, Any] | None = None
    face_mask: str | None = None
    head_region: dict[str, Any] | None = None

    def retry(self, new_url: str) -> BookLayer:
        """Return new layer with new_url active and old image pushed to history."""
        history = list(self.history)
        if self.image_url:
            history.append(self.image_url)
        return BookLayer(
            name=self.name,
            layer_type=self.layer_type,
            image_url=new_url,
            prompt=self.prompt,
            z_index=self.z_index,
            visible=self.visible,
            quality=self.quality,
            history=history,
            slot=self.slot,
            pose=self.pose,
            face_mask=self.face_mask,
            head_region=self.head_region,
        )

    def upgrade(self, new_url: str) -> BookLayer:
        """Return new layer upgraded to final quality; history preserved."""
        upgraded = self.retry(new_url)
        upgraded.quality = "final"
        return upgraded


# ─────────────────────────────────────────────────────────────────────
# Value objects
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TextConfig:
    content: str
    font: str = "sans-serif"
    size: int = 48
    color: str = "#FFFFFF"
    weight: str = "normal"
    alignment: str = "center"
    shadow_color: str | None = None
    shadow_offset: tuple[int, int] = (2, 2)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    display_name: str
    provider: str
    supports_generate: bool = True
    supports_refine: bool = False
    tier_class: str = "draft"
    cost_per_image_usd: float = 0.0
    is_free: bool = True


# ─────────────────────────────────────────────────────────────────────
# Mutable records
# ─────────────────────────────────────────────────────────────────────


@dataclass
class CanvasRecord:
    id: str
    name: str
    width: int
    height: int
    background_color: str = "#FFFFFF"
    org_id: str = ""
    layer_count: int = 0
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_archived(self) -> bool:
        return self.archived_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "background_color": self.background_color,
            "org_id": self.org_id,
            "layer_count": self.layer_count,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class LayerRecord:
    id: str
    canvas_id: str
    name: str
    layer_type: str = LayerType.BACKGROUND
    z_index: int = 0
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    blend_mode: str = BlendMode.NORMAL
    visible: bool = True
    locked: bool = False
    image_path: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    model_id: str | None = None
    tier: str = CanvasTier.DRAFT
    generation_seed: int | None = None
    text_config: TextConfig | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        tc: dict[str, Any] | None = None
        if self.text_config is not None:
            tc = {
                "content": self.text_config.content,
                "font": self.text_config.font,
                "size": self.text_config.size,
                "color": self.text_config.color,
                "weight": self.text_config.weight,
                "alignment": self.text_config.alignment,
                "shadow_color": self.text_config.shadow_color,
                "shadow_offset": list(self.text_config.shadow_offset),
            }
        return {
            "id": self.id,
            "canvas_id": self.canvas_id,
            "name": self.name,
            "layer_type": self.layer_type,
            "z_index": self.z_index,
            "x": self.x,
            "y": self.y,
            "scale": self.scale,
            "rotation": self.rotation,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
            "visible": self.visible,
            "locked": self.locked,
            "image_path": self.image_path,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "model_id": self.model_id,
            "tier": self.tier,
            "generation_seed": self.generation_seed,
            "text_config": tc,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class GenerationJobRecord:
    id: str
    layer_id: str
    canvas_id: str
    action: str = JobAction.GENERATE
    status: str = JobStatus.PENDING
    model_id: str = ""
    prompt: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result_paths: list[str] = field(default_factory=list)
    selected_index: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # SPEC-203: lease/retry fields
    attempts: int = 0
    max_attempts: int = 3
    leased_by: str | None = None
    lease_expires_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)

    def is_active(self) -> bool:
        return self.status in (JobStatus.PENDING, JobStatus.RUNNING)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer_id": self.layer_id,
            "canvas_id": self.canvas_id,
            "action": self.action,
            "status": self.status,
            "model_id": self.model_id,
            "prompt": self.prompt,
            "params": self.params,
            "result_paths": self.result_paths,
            "selected_index": self.selected_index,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CompositeResult:
    canvas_id: str
    image_bytes: bytes
    width: int
    height: int
    layer_snapshot: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────────────────────────────
# Domain errors
# ─────────────────────────────────────────────────────────────────────


class CanvasError(AgentError):
    code = "CANVAS_ERROR"


class CanvasNotFoundError(CanvasError):
    code = "CANVAS_NOT_FOUND"


class CanvasArchivedError(CanvasError):
    code = "CANVAS_ARCHIVED"


class CanvasHasLayersError(CanvasError):
    code = "CANVAS_HAS_LAYERS"


class LayerNotFoundError(CanvasError):
    code = "LAYER_NOT_FOUND"


class LayerLimitExceededError(CanvasError):
    code = "LAYER_LIMIT_EXCEEDED"


class LayerLockedError(CanvasError):
    code = "LAYER_LOCKED"


class DuplicateZIndexError(CanvasError):
    code = "DUPLICATE_Z_INDEX"


class IncompleteReorderError(CanvasError):
    code = "INCOMPLETE_REORDER"


class JobNotFoundError(CanvasError):
    code = "JOB_NOT_FOUND"


class JobInProgressError(CanvasError):
    code = "JOB_IN_PROGRESS"


class JobNotDoneError(CanvasError):
    code = "JOB_NOT_DONE"


class JobAlreadyTerminalError(CanvasError):
    code = "JOB_ALREADY_TERMINAL"


class TextLayerNoGenError(CanvasError):
    code = "TEXT_LAYER_NO_GEN"


class UnknownModelError(CanvasError):
    code = "UNKNOWN_MODEL"


class PromptBlockedError(CanvasError):
    code = "PROMPT_BLOCKED"


class RefineNoSourceError(CanvasError):
    code = "REFINE_NO_SOURCE"


class VariantIndexOutOfRangeError(CanvasError):
    code = "VARIANT_INDEX_OUT_OF_RANGE"


class UnsupportedFormatError(CanvasError):
    code = "UNSUPPORTED_FORMAT"


# ─────────────────────────────────────────────────────────────────────
# Layer-model domain errors (ADR-039 §9)
# ─────────────────────────────────────────────────────────────────────


class UnknownLayerKindError(CanvasError):
    code = "UNKNOWN_LAYER_KIND"


class MissingAnchorError(CanvasError):
    code = "MISSING_ANCHOR"


class MissingSocketError(CanvasError):
    code = "MISSING_SOCKET"


class OcclusionCycleError(CanvasError):
    code = "OCCLUSION_CYCLE"


class AssetSheetNotFoundError(CanvasError):
    code = "ASSET_SHEET_NOT_FOUND"


class AssetDefinitionNotFoundError(CanvasError):
    code = "ASSET_DEFINITION_NOT_FOUND"


class WorldStyleConflictError(CanvasError):
    code = "WORLD_STYLE_CONFLICT"


class SkinBindingError(CanvasError):
    code = "SKIN_BINDING_ERROR"


class PoseGeometryMismatchError(CanvasError):
    code = "POSE_GEOMETRY_MISMATCH"


# ─────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────

_MAX_LAYERS = 50
_MIN_DIM = 64
_MAX_DIM = 8192
_VALID_EXPORT_FORMATS = frozenset({"png", "webp", "jpg", "jpeg"})
_MAX_REFERENCE_PHOTOS = 5
# First-pass reasonable default cap on images requested per generation call
# (no existing "max images per request" constant elsewhere to reuse).
_MAX_GENERATE_COUNT = 20


def validate_canvas_dimensions(width: int, height: int) -> None:
    for dim_name, dim_value in (("width", width), ("height", height)):
        if not (_MIN_DIM <= dim_value <= _MAX_DIM):
            msg = f"{dim_name} must be between {_MIN_DIM} and {_MAX_DIM}, got {dim_value}"
            raise ValueError(msg)
        if dim_value % 8 != 0:
            msg = f"{dim_name} must be divisible by 8, got {dim_value}"
            raise ValueError(msg)


def normalise_rotation(degrees: float) -> float:
    return degrees % 360.0
