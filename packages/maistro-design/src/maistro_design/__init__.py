"""maistro-design — composable design skills + design systems + canvas engine.

Public API surface. Import from here for stable, ADR-061-governed access.
"""

import importlib.metadata
from typing import Any

# Single source of truth for version — read from installed package metadata.
try:
    __version__ = importlib.metadata.version("maistro-design")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - editable/unbuilt checkout
    __version__ = "0.9.0-dev"

# The #774 brief contract keeps the top-level names it spec'd
# (SPEC-092826: `CreativeBrief`, `CreativeBriefError`, `CreativeBriefStore`).
from maistro_design.brief import (
    ArtifactProjection,
    ArtifactRequest,
    ArtifactRequestNotFoundError,
    BriefContractError,
    BriefReference,
    BriefVersionConflictError,
    CreativeBrief,
    CreativeBriefError,
    CrossWorkspaceReferenceError,
    EvidenceReference,
    ProjectionOverride,
    ProtectedFieldOverrideError,
    RequiredFact,
)
from maistro_design.engine import DesignEngine
from maistro_design.protocols import (
    DesignEngineProtocol,
    DesignProjectStore,
    DesignSkillRegistry,
    DesignSystemRegistry,
    HTMLRenderer,
    SVGRenderer,
    TypographyRenderer,
)
from maistro_design.providers import OpenDesignConfig, OpenDesignProvider
from maistro_design.renderers import (
    NATIVE_SLOTS,
    RendererDiscovery,
    RendererRegistry,
    RenderProvider,
    RenderProviderError,
    RenderSlotUnavailableError,
    available_skills,
)
from maistro_design.scan import ScanReport, scan_design_output, scan_design_text
from maistro_design.skills.builtins import load_builtins
from maistro_design.skills.registry import InMemoryDesignSkillRegistry
from maistro_design.systems.importer import (
    import_from_catalog,
    import_open_design_system,
    load_bundled,
    load_catalog,
    scan_design_system_content,
)
from maistro_design.systems.loader import DesignSystemLoader
from maistro_design.systems.registry import InMemoryDesignSystemRegistry
from maistro_design.trust import (
    InMemoryTrustBanishList,
    InMemoryTrustReviewQueue,
    TrustReviewRecord,
    TrustTier,
)
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    CatalogImportPolicyError,
    ColorToken,
    DesignError,
    DesignOutput,
    DesignOutputShapeError,
    DesignProject,
    DesignSkill,
    DesignSystem,
    DesignSystemNotFoundError,
    DiscoveryField,
    DiscoveryIncompleteError,
    DiscoveryResult,
    IncompatibleDesignSystemError,
    OutputFormat,
    RenderSlot,
    SkillMode,
    SkillModeError,
    SkillNotFoundError,
    SpacingToken,
    TrustBannedError,
    TrustUpgradeRequiredError,
    TypographyToken,
)
from maistro_design.versions import (
    AgentWorkInputs,
    ArtifactLock,
    ArtifactLockConflict,
    ArtifactVersion,
    ArtifactVersionError,
    ArtifactVersionExistsError,
    ArtifactVersionNotFoundError,
    BranchControl,
    BranchStateView,
    ChangeKind,
    ChangeOrigin,
    ControlMode,
    CreativeArtifactService,
    GuidanceRecord,
    LockScope,
    LockStateError,
    VersionState,
    VersionStateError,
)

__all__ = [
    "NATIVE_SLOTS",
    "AgentWorkInputs",
    "ArtifactKind",
    "ArtifactLock",
    "ArtifactLockConflict",
    "ArtifactNode",
    "ArtifactProjection",
    "ArtifactRequest",
    "ArtifactRequestNotFoundError",
    "ArtifactVersion",
    "ArtifactVersionError",
    "ArtifactVersionExistsError",
    "ArtifactVersionNotFoundError",
    "BranchControl",
    "BranchStateView",
    "BriefContractError",
    "BriefReference",
    "BriefVersionConflictError",
    "CatalogImportPolicyError",
    "ChangeKind",
    "ChangeOrigin",
    "ColorToken",
    "ControlMode",
    "CreativeArtifactService",
    "CreativeBrief",
    "CreativeBriefError",
    "CreativeBriefStore",
    "CreativeGraphPlan",
    "CrossWorkspaceReferenceError",
    "DesignEngine",
    "DesignEngineProtocol",
    "DesignError",
    "DesignOutput",
    "DesignOutputShapeError",
    "DesignProject",
    "DesignProjectStore",
    "DesignSkill",
    "DesignSkillRegistry",
    "DesignSystem",
    "DesignSystemLoader",
    "DesignSystemNotFoundError",
    "DesignSystemRegistry",
    "DiscoveryField",
    "DiscoveryIncompleteError",
    "DiscoveryResult",
    "EvidenceReference",
    "GuidanceRecord",
    "HTMLRenderer",
    "InMemoryDesignSkillRegistry",
    "InMemoryDesignSystemRegistry",
    "InMemoryTrustBanishList",
    "InMemoryTrustReviewQueue",
    "IncompatibleDesignSystemError",
    "LockScope",
    "LockStateError",
    "OpenDesignConfig",
    "OpenDesignProvider",
    "OutputFormat",
    "PgCreativeBriefStore",
    "PgDesignProjectStore",
    "ProjectionOverride",
    "ProtectedFieldOverrideError",
    "RenderProvider",
    "RenderProviderError",
    "RenderSlot",
    "RenderSlotUnavailableError",
    "RendererDiscovery",
    "RendererRegistry",
    "RequiredFact",
    "SVGRenderer",
    "ScanReport",
    "SkillMode",
    "SkillModeError",
    "SkillNotFoundError",
    "SpacingToken",
    "TrustBannedError",
    "TrustReviewRecord",
    "TrustTier",
    "TrustUpgradeRequiredError",
    "TypographyRenderer",
    "TypographyToken",
    "VersionState",
    "VersionStateError",
    "__version__",
    "available_skills",
    "import_from_catalog",
    "import_open_design_system",
    "load_builtins",
    "load_bundled",
    "load_catalog",
    "scan_design_output",
    "scan_design_system_content",
    "scan_design_text",
]


def __getattr__(name: str) -> Any:
    """Lazy-load the SQLAlchemy-backed PG stores to avoid importing sqlalchemy eagerly."""
    if name == "PgDesignProjectStore":
        from maistro_design.stores import PgDesignProjectStore

        return PgDesignProjectStore
    if name == "PgArtifactVersionStore":
        from maistro_design.version_store import PgArtifactVersionStore

        return PgArtifactVersionStore
    if name == "PgCreativeBriefStore":
        from maistro_design.brief_store import PgCreativeBriefStore

        return PgCreativeBriefStore
    if name == "CreativeBriefStore":
        from maistro_design.protocols import CreativeBriefStore

        return CreativeBriefStore
    if name in {
        "ArtifactProvenanceRecord",
        "CreativeGraphPlan",
        "InvalidationReport",
        "artifact_provenance",
        "channel_family",
        "instantiate_creative_graph",
        "invalidated_requests",
        "plan_creative_graph",
        "run_creative_graph",
    }:
        import maistro_design.creative_graph as creative_graph

        return getattr(creative_graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
