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
from maistro_design.scan import ScanReport, scan_design_output
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

__all__ = [
    "NATIVE_SLOTS",
    "ArtifactKind",
    "ArtifactNode",
    "ColorToken",
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
    "HTMLRenderer",
    "InMemoryDesignSkillRegistry",
    "InMemoryDesignSystemRegistry",
    "InMemoryTrustBanishList",
    "InMemoryTrustReviewQueue",
    "IncompatibleDesignSystemError",
    "OpenDesignConfig",
    "OpenDesignProvider",
    "OutputFormat",
    "PgDesignProjectStore",
    "RenderProvider",
    "RenderProviderError",
    "RenderSlot",
    "RenderSlotUnavailableError",
    "RendererDiscovery",
    "RendererRegistry",
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
    "__version__",
    "available_skills",
    "import_from_catalog",
    "import_open_design_system",
    "load_builtins",
    "load_bundled",
    "load_catalog",
    "scan_design_output",
    "scan_design_system_content",
]


def __getattr__(name: str) -> Any:
    """Lazy-load PgDesignProjectStore to avoid requiring sqlalchemy at import time."""
    if name == "PgDesignProjectStore":
        from maistro_design.stores import PgDesignProjectStore

        return PgDesignProjectStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
