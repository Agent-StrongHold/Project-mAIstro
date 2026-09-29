"""Domain packs (M7-A4, #793) — product, game, and book as bundles of one Run.

Public surface:

- `PackRegistry` — the one registry; `builtin()` loads the in-repo YAML
  manifests, `summaries()` is the Design Studio selector payload.
- `DomainPack` / `PackId` / `PackGraphShape` / `RubricDimension` — the pack
  contract (`types`).
- `GoalRubricCatalog` — a pack's default Rubric dimensions instantiated onto
  a canonical Goal, identity minted per instantiation (`rubric`).
- `pack_graph_template` — a pack's Graph shape as a canonical
  `GraphTemplate`, executable by the canonical durable executor (`graphs`).

Import shape mirrors the package's own layering: `types` (contract) ←
`rubric` (Goal-scoped instance) and ← `graphs` (canonical template
projection), with `registry` composing them.
"""

from __future__ import annotations

from maistro_design.packs.graphs import pack_graph_template
from maistro_design.packs.registry import (
    PackManifestError,
    PackRegistry,
    PackRegistryError,
    UnknownPackError,
    parse_manifest,
)
from maistro_design.packs.rubric import GoalRubricCatalog, GoalRubricDimension
from maistro_design.packs.types import (
    DomainPack,
    ExecuteBackend,
    FencePoint,
    PackGraphShape,
    PackId,
    PackPhase,
    PackPhaseName,
    PackSummary,
    RubricDimension,
)

__all__ = [
    "DomainPack",
    "ExecuteBackend",
    "FencePoint",
    "GoalRubricCatalog",
    "GoalRubricDimension",
    "PackGraphShape",
    "PackId",
    "PackManifestError",
    "PackPhase",
    "PackPhaseName",
    "PackRegistry",
    "PackRegistryError",
    "PackSummary",
    "RubricDimension",
    "UnknownPackError",
    "pack_graph_template",
    "parse_manifest",
]
