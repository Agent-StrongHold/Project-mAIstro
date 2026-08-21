"""maistro-canvas: standalone book builder with AI image generation pipeline.

Standalone product that can run on a mini-PC with a P40 image gen server.
Uses canvas protocols from maistro-core for the image generation pipeline.
"""

from __future__ import annotations

import importlib.metadata

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-canvas")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"

from maistro_canvas.export import (
    ExporterDependencyError,
    ExportLayer,
    ExportPage,
    ExportText,
    export_html,
    export_pptx,
)
from maistro_canvas.layers import (
    POSE_GEOMETRY_FOR_KIND,
    Anchor,
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    BackgroundComposition,
    CharacterPose,
    ChildProfile,
    FoundationFootprint,
    GroundPlane,
    LayerKind,
    OcclusionHint,
    PersonalizationKind,
    PersonalizationSlot,
    PoseGeometry,
    RenderStyle,
    Slot,
    Socket,
    StyleVolume,
    Transform,
    WheelAnchors,
    WorldStyle,
    WorldStylePartial,
    layer_type_to_kind,
    merge_world_style,
)
from maistro_canvas.protocols import (
    AssetRegistry,
    AssetSheetService,
    CanvasStore,
    CompositorService,
    ImageData,
    ImageGenClient,
    PersonalizationCompiler,
)
from maistro_canvas.types import (
    AssetDefinitionNotFoundError,
    AssetSheetNotFoundError,
    BlendMode,
    CanvasError,
    CanvasRecord,
    CanvasTier,
    GenerationJobRecord,
    JobAction,
    JobStatus,
    LayerRecord,
    LayerType,
    MissingAnchorError,
    MissingSocketError,
    ModelInfo,
    OcclusionCycleError,
    PoseGeometryMismatchError,
    SkinBindingError,
    TextConfig,
    UnknownLayerKindError,
    WorldStyleConflictError,
    normalise_rotation,
    validate_canvas_dimensions,
)

__all__ = [
    "POSE_GEOMETRY_FOR_KIND",
    # ADR-039 layer model
    "Anchor",
    "AssetDefinition",
    # ADR-039 errors
    "AssetDefinitionNotFoundError",
    "AssetInstance",
    "AssetRegistry",
    "AssetSheet",
    "AssetSheetNotFoundError",
    "AssetSheetService",
    "BackgroundComposition",
    # Existing canvas primitives
    "BlendMode",
    "CanvasError",
    "CanvasRecord",
    "CanvasStore",
    "CanvasTier",
    "CharacterPose",
    "ChildProfile",
    "CompositorService",
    # Structured exporters (SPEC-070426-457b)
    "ExportLayer",
    "ExportPage",
    "ExportText",
    "ExporterDependencyError",
    "FoundationFootprint",
    "GenerationJobRecord",
    "GroundPlane",
    "ImageData",
    "ImageGenClient",
    "JobAction",
    "JobStatus",
    "LayerKind",
    "LayerRecord",
    "LayerType",
    "MissingAnchorError",
    "MissingSocketError",
    "ModelInfo",
    "OcclusionCycleError",
    "OcclusionHint",
    "PersonalizationCompiler",
    "PersonalizationKind",
    "PersonalizationSlot",
    "PoseGeometry",
    "PoseGeometryMismatchError",
    "RenderStyle",
    "SkinBindingError",
    "Slot",
    "Socket",
    "StyleVolume",
    "TextConfig",
    "Transform",
    "UnknownLayerKindError",
    "WheelAnchors",
    "WorldStyle",
    "WorldStyleConflictError",
    "WorldStylePartial",
    "__version__",
    "export_html",
    "export_pptx",
    "layer_type_to_kind",
    "merge_world_style",
    "normalise_rotation",
    "validate_canvas_dimensions",
]
