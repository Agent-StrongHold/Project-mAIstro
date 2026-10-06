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
- The M9-F3 (#968) Workspace lifecycle (`lifecycle` + `service`):
  `PackLifecycleService` over a `PackLifecycleStore` — per-Workspace
  activation/configuration/upgrade/disable/removal with audited, atomic
  transitions and snapshot-anchored new-use gates.

Import shape mirrors the package's own layering: `types` (contract) ←
`rubric` (Goal-scoped instance) and ← `graphs` (canonical template
projection), with `registry` composing them and `lifecycle`/`service`
layering the Workspace lifecycle over all of it.
"""

from __future__ import annotations

from maistro.graph.definitions import Node
from maistro_design.packs.graphs import pack_graph_template
from maistro_design.packs.lifecycle import (
    InMemoryPackLifecycleStore,
    InvalidLifecycleOperation,
    PackActivationRecord,
    PackConfigurationInvalid,
    PackIdentityConflict,
    PackLifecycleError,
    PackLifecycleState,
    PackLifecycleStore,
    PackManifestSnapshot,
    PackNotEnabled,
    PackRegistryUpgradeUnavailable,
    PackTransition,
    PackTransitionKind,
    PackUpgradeBlocked,
    PackUpgradePreflight,
    SnapshotIntegrityError,
    WorkspacePackConfiguration,
    pack_from_snapshot,
    parse_pack_version,
    snapshot_pack,
)
from maistro_design.packs.registry import (
    PackManifestError,
    PackRegistry,
    PackRegistryError,
    UnknownPackError,
    parse_manifest,
)
from maistro_design.packs.rubric import GoalRubricCatalog, GoalRubricDimension
from maistro_design.packs.service import PackLifecycleService
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

# Vulture scan input, hosted in this reachable module rather than a loose
# ``_vulture_whitelist.py`` sibling (the reachability baseline may only grow
# behind a prior landed authorization, and a second loose file would collide
# with maistro-core's). Mirrors packages/maistro-core/src/_vulture_whitelist.py:
# the closed enums' members are the #793 pack contract — manifests name them by
# YAML value and the registry iterates the enum dynamically, so no scanned call
# site names a member literally — and the registry methods, pydantic validators,
# the A2 Goal-instantiation seam, and the canonical binding_ids field are
# framework- or route-consumed surfaces (packages/hive-conductor's Design
# Studio route sits outside the ``packages/*/src`` scan).
_VULTURE_PACK_IDS = (PackId.PRODUCT, PackId.GAME, PackId.BOOK)
_VULTURE_EXECUTE_BACKENDS = (
    ExecuteBackend.CANVAS,
    ExecuteBackend.BUILDERS,
    ExecuteBackend.FILE_ARTIFACT_WRITER,
    ExecuteBackend.TEXT_ARTIFACT_TREE,
    ExecuteBackend.MEDIA,
)
_VULTURE_WHITELIST = (
    PackRegistry.builtin,
    PackRegistry.summaries,
    DomainPack._validate_pack,
    PackGraphShape._validate_shape,
    DomainPack.instantiate_rubric_catalog,
    # M9-F3 (#968) lifecycle surface: the service and store methods are the
    # governed seams deployments and the conformance tests consume; the
    # Design Studio route sits outside the ``packages/*/src`` scan, so the
    # names stay referenced here the same way the #793 contract names are.
    # Method names are deliberately suffixed (``enable_pack`` not ``enable``):
    # vulture's used-name matching is scan-global, and an unsuffixed name
    # would mark unrelated same-named methods elsewhere in the tree as used,
    # silently shrinking banked debt the ledger rightly demands back.
    PackLifecycleService.enable_pack,
    PackLifecycleService.disable_pack,
    PackLifecycleService.remove_pack,
    PackLifecycleService.upgrade_pack,
    PackLifecycleService.configure_pack,
    PackLifecycleService.preflight_upgrade,
    PackLifecycleService.record,
    PackLifecycleService.workspace_records,
    PackLifecycleService.transitions,
    PackLifecycleService.require_enabled,
    PackLifecycleService.materialize_template,
    PackLifecycleService.instantiate_catalog,
    InMemoryPackLifecycleStore.commit,
    InMemoryPackLifecycleStore.get_record,
    InMemoryPackLifecycleStore.records_for_workspace,
    InMemoryPackLifecycleStore.transitions_for,
    InMemoryPackLifecycleStore.next_seq,
    WorkspacePackConfiguration._no_duplicate_dimension_ids,
    PackUpgradePreflight.target_version,
    PackUpgradePreflight.unauthorized_backends,
    PackUpgradePreflight.dropped_rubric_dimensions,
    pack_from_snapshot,
    snapshot_pack,
    parse_pack_version,
    # A pydantic field has no class-level attribute (pydantic v2), so the
    # reference goes through an unvalidated instance: the field is the
    # canonical binding-reference surface pack_graph_template writes.
    # `node_type` is the one required Node field, so `model_construct` needs
    # it named even though nothing here validates or executes the instance.
    Node.model_construct(node_type="").binding_ids,
)

__all__ = [
    "DomainPack",
    "ExecuteBackend",
    "FencePoint",
    "GoalRubricCatalog",
    "GoalRubricDimension",
    "InMemoryPackLifecycleStore",
    "InvalidLifecycleOperation",
    "PackActivationRecord",
    "PackConfigurationInvalid",
    "PackGraphShape",
    "PackId",
    "PackIdentityConflict",
    "PackLifecycleError",
    "PackLifecycleService",
    "PackLifecycleState",
    "PackLifecycleStore",
    "PackManifestError",
    "PackManifestSnapshot",
    "PackNotEnabled",
    "PackPhase",
    "PackPhaseName",
    "PackRegistry",
    "PackRegistryError",
    "PackRegistryUpgradeUnavailable",
    "PackSummary",
    "PackTransition",
    "PackTransitionKind",
    "PackUpgradeBlocked",
    "PackUpgradePreflight",
    "RubricDimension",
    "SnapshotIntegrityError",
    "UnknownPackError",
    "WorkspacePackConfiguration",
    "pack_from_snapshot",
    "pack_graph_template",
    "parse_manifest",
    "parse_pack_version",
    "snapshot_pack",
]
