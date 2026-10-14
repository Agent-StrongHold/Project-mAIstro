"""Installable domain-pack contracts over canonical objects (M9-F1, issue #966).

A **domain pack** is an out-of-tree bundle of reusable *defaults* — Graph
shapes, Persona templates, Rubric dimension catalogs — that installs through
the M9 governed-extension machinery and instantiates onto the canonical
Goal/Graph/Persona/Rubric objects. It is the installable generalization of
the in-repo pack contract (`maistro_design.packs`, #793): the shipped
product/game/book packs are in-repo data with a closed id enum; this module
is the contract for packs whose bytes come from outside the repository, so
identity is publisher-namespaced instead of enum-closed.

The invariants this module enforces (each pinned by
`packages/maistro-core/tests/extensions/test_pack_contracts.py`):

- **A pack manifest is data, validated before any code runs.** Parsing is
  fail-closed over raw bytes in exactly the discipline of
  :mod:`maistro.extensions.manifest`: unknown keys are rejections, never
  ignored lines; the envelope version is pinned; asset payloads are validated
  *as the canonical objects they will become* (a scratch ``GraphTemplate`` /
  ``Persona`` / ``RubricSemantic`` is constructed and discarded at
  inspection), so a pack cannot carry a payload canonical validation would
  refuse. Nothing here imports or executes pack code — a pack's runtime
  behavior, if any, stays behind the governed loader of M9-B2 (#953).
- **No second identity scheme.** A pack never mints or carries canonical
  identity. Instantiation mints canonical ids the canonical way (fresh uuid
  hex for template/persona/rubric ids, bound to caller-named Workspaces);
  pack-local ``asset_id`` values never replace a canonical object id — they
  ride only in provenance fields.
- **Version-addressable assets with provenance.** Assets are addressed by
  ``(asset_id, version)``; every instantiated object carries the pack's
  publisher/version provenance (``GraphTemplate`` metadata, ``Persona``
  ``source_template_*``/``extension_metadata``, Rubric
  ``ProvenanceOrigin.PACK`` + the full snapshot identity on
  ``RubricProvenance`` — publisher, pack version, asset id/version, and
  the manifest digest — so rubrics instantiated from different versions
  of the same pack are provenance-distinguishable).
- **The manifest snapshot is anchored to its bytes.** The snapshot's outer
  dataclasses and tuples are frozen and persona payload trees are frozen
  recursively; the one part of the tree that cannot be frozen here (the
  canonical ``RubricDimension`` objects inside a rubric asset — a canonical
  model, not this contract's to re-freeze) is closed by construction:
  ``PackManifest.asset`` resolves every use against a pristine re-parse of
  ``raw``, so a caller who mutates a stored asset cannot make new
  instantiations diverge from the bytes ``source_sha256`` names.
- **Dependencies resolve through the M9 compatibility machinery.** A pack
  declares ``api_version`` plus dependencies on other extensions (packs are
  extensions that ship assets; capability providers are extensions), and
  resolution is
  :func:`maistro.extensions.compatibility.evaluate_compatibility` over the
  pack's extension view — never a second resolver.
- **Disable stops new use, deletes nothing.** The registry's disable flips
  the pack's own record only; instantiated objects live in the canonical
  stores and keep their provenance, and no API here can reach them.
- **No private authority.** The manifest schema has no executor, store, or
  authority field (unknown keys fail closed), instantiation is pure (it
  returns canonical objects; persistence happens only through the canonical
  stores the caller already owns), and this module accepts no store, no
  executor, and no Goal/Persona/Rubric authority — a pack can decorate the
  canonical objects but cannot become a second one.

Placement: ``maistro.extensions`` is the M9 extension namespace (M9-B1/B2
records and lifecycle, #952/#953); the pack contract is its asset-bearing
subtype (#966), and the Workspace-scoped activation/config/upgrade lifecycle
that will drive it is M9-F3 (#968).
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NoReturn

from pydantic import ValidationError

from maistro.extensions.compatibility import (
    CompatibilityPolicy,
    CompatibilityReport,
    evaluate_compatibility,
)
from maistro.extensions.manifest import SEMVER_RE, sha256_hex
from maistro.extensions.types import ExtensionDependency, ExtensionManifest
from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro.ontology.rubric import (
    NumericScale,
    PassFailScale,
    ProvenanceOrigin,
    RubricAggregation,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricScale,
    RubricSemantic,
    ScoringMethod,
)

if TYPE_CHECKING:
    from maistro.personas.model import Persona

__all__ = [
    "SUPPORTED_PACK_MANIFEST_VERSION",
    "InstallablePackRegistry",
    "PackAsset",
    "PackAssetKind",
    "PackAssetUnknown",
    "PackContractError",
    "PackDisabledError",
    "PackGraphDefinition",
    "PackGraphNode",
    "PackIdentityConflict",
    "PackIncompatible",
    "PackInstallRecord",
    "PackManifest",
    "PackManifestRejected",
    "PackPersonaDefinition",
    "PackProvenance",
    "PackRubricDefinition",
    "PackState",
    "evaluate_pack_compatibility",
    "inspect_pack_manifest",
    "instantiate_graph_asset",
    "instantiate_persona_asset",
    "instantiate_rubric_asset",
    "pack_extension_view",
]

#: The only pack-manifest envelope this platform accepts. Unknown versions
#: fail closed — a forward-compat guess would install assets nobody read.
SUPPORTED_PACK_MANIFEST_VERSION = 1

#: The manifest subtype discriminator. A pack manifest *is* an extension
#: manifest that ships canonical-object assets; the ``kind`` field says so.
PACK_MANIFEST_KIND = "domain-pack"

#: Reserved workspace/id value the inspection-time canonical probe uses.
#: It is never a real Workspace: the canonical objects built on it are
#: discarded before :func:`inspect_pack_manifest` returns.
_PROBE = "pack-manifest-inspection-probe"

#: Pack-local asset ids: lowercase slug, hyphen-separated. Namespaced under
#: the pack id at every use site, never usable as a canonical id.
_ASSET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")

#: Publisher slugs — the same grammar the extension manifest enforces.
_PUBLISHER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

#: Capability/authority tokens — the same closed-shape grammar extension
#: manifests use for permission names.
_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

#: Dependency ids — the extension-id grammar, so a pack can only name
#: extension/platform identities the compatibility machinery understands.
_EXTENSION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

#: Pack-id name segment (the ``publisher.name`` tail). The publisher half
#: reuses ``_PUBLISHER_RE`` so any publisher slug an extension manifest
#: accepts (including hyphenated ids like ``pub-1``) can own packs.
_PACK_SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class PackContractError(RuntimeError):
    """Base class for installable-pack contract failures."""


class PackManifestRejected(PackContractError):
    """The manifest bytes are not a valid domain-pack manifest.

    Raised only from parsing, with the same fail-closed posture as the
    extension manifest: a document that cannot be parsed has no pack
    identity to key an install with, so it is refused at the door.
    """


class PackAssetUnknown(PackContractError):
    """No installed pack asset answers the requested (asset_id, version)."""


class PackDisabledError(PackContractError):
    """The pack is disabled in this registry: no new use, nothing deleted."""


class PackIdentityConflict(PackContractError):
    """The same (pack_id, version) was installed again with different bytes.

    Mirrors the M9-B1 rule for extension packages: a semantic version alone
    does not name a pack — the manifest digest is part of the identity, and
    a second body must never silently masquerade as the first.
    """


class PackIncompatible(PackContractError):
    """The M9 compatibility machinery refused the pack for this platform."""


def _reject(detail: str) -> PackManifestRejected:
    return PackManifestRejected(f"invalid domain-pack manifest: {detail}")


def _require_str(document: Mapping[str, Any], key: str) -> str:
    value = document[key]
    if not isinstance(value, str) or not value.strip():
        raise _reject(f"{key} must be a non-empty string")
    return value


def _require_finite(value: Any, what: str) -> float:
    """Reject non-finite pack numbers (``1e400``/``Infinity``/``NaN`` in JSON)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise _reject(f"{what} must be a finite number")
    return float(value)


def _validate_semver(value: object, what: str) -> str:
    if not isinstance(value, str) or SEMVER_RE.match(value) is None:
        raise _reject(f"{what} must be semver X.Y.Z, got {value!r}")
    return value


def _semver_key(version: str) -> tuple[int, int, int]:
    """Sort key for "highest active version" resolution (parsing validated)."""
    match = SEMVER_RE.match(version)
    assert match is not None, "only parsed semvers reach this helper"
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _raise_pack_unavailable(
    pack_id: str,
    version: str | None,
    installed: list[tuple[tuple[str, str], PackInstallRecord]],
) -> NoReturn:
    """The no-candidate half of ``InstallablePackRegistry._require_record``.

    Installed but not active: the disabled record itself answers, with the
    operator's note surfaced verbatim. Never installed: the request was
    refused, nothing is recorded.
    """
    if installed:
        disabled = max(installed, key=lambda entry: _semver_key(entry[0][1]))[1]
        detail = f"; note: {disabled.note}" if disabled.note else ""
        raise PackDisabledError(f"pack {pack_id!r} is disabled in this registry{detail}")
    raise PackDisabledError(
        f"pack {pack_id!r}"
        + (f" at version {version!r}" if version else "")
        + " has no active install in this registry"
    )


# --------------------------------------------------------------------------
# Asset definitions: one closed kind vocabulary, one payload per kind
# --------------------------------------------------------------------------


class PackAssetKind(StrEnum):
    """The canonical object kinds a pack may ship defaults for.

    The graph member is ``GRAPH_TEMPLATE`` — the canonical object a graph
    asset instantiates as — rather than a bare ``GRAPH`` whose name would
    collide, at the scanner's name-level matching, with unrelated banked
    ``GRAPH`` findings elsewhere in the tree.
    """

    GRAPH_TEMPLATE = "graph"
    PERSONA = "persona"
    RUBRIC = "rubric"


@dataclass(frozen=True)
class PackGraphNode:
    """One node of a pack's Graph asset, in canonical shape."""

    node_id: str
    node_type: str
    name: str = ""


@dataclass(frozen=True)
class PackGraphDefinition:
    """A Graph shape default. Instantiated as a canonical ``GraphTemplate``."""

    name: str
    nodes: tuple[PackGraphNode, ...]
    edges: tuple[tuple[str, str], ...]
    description: str = ""
    entry_node: str | None = None


@dataclass(frozen=True)
class PackPersonaDefinition:
    """A Persona template default. Instantiated as a canonical ``Persona``.

    ``payload`` is the validated Persona-shaped mapping, kept string-keyed
    on purpose: instantiation feeds it to the canonical model as keyword
    arguments built from these string keys, so the scanner's name-level
    analysis keeps attributing ``purpose``/``style_guidance`` usages to the
    canonical Persona model that owns them (their banked debt lives there),
    not to this pass-through payload. The tree is frozen recursively
    (``MappingProxyType`` over tuples): a caller holding the manifest
    snapshot cannot mutate a stored payload in place.
    """

    name: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class PackRubricDefinition:
    """A Rubric default catalog. Instantiated as a canonical ``RubricSemantic``."""

    name: str
    dimensions: tuple[RubricDimension, ...]
    gate_pass_threshold: float
    veto_dimension_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackAsset:
    """One version-addressable asset: ``(asset_id, version)`` + payload."""

    asset_id: str
    version: str
    kind: PackAssetKind
    graph: PackGraphDefinition | None = None
    persona: PackPersonaDefinition | None = None
    rubric: PackRubricDefinition | None = None


def _parse_graph_node(item: object, node_ids: set[str]) -> PackGraphNode:
    """Keys, identity, and name type for one graph node — the per-item half
    of the node-list pass, extracted so each function stays under the
    complexity floor (same decomposition style as ``_validate_graph_head``)."""
    if not isinstance(item, dict) or set(item) - {"node_id", "node_type", "name"}:
        raise _reject("each graph node must have only node_id, node_type, name")
    # The shape check above only refuses *unknown* keys; without this, a
    # node missing node_id/node_type reaches _require_str's direct index
    # and a raw KeyError escapes the typed PackManifestRejected boundary.
    missing_node = [key for key in ("node_id", "node_type") if key not in item]
    if missing_node:
        raise _reject(f"missing graph node keys: {missing_node}")
    node_id = _require_str(item, "node_id")
    if _ASSET_ID_RE.match(node_id) is None:
        raise _reject(f"malformed graph node_id: {node_id!r}")
    if node_id in node_ids:
        raise _reject(f"duplicate graph node_id: {node_id!r}")
    node_name = item.get("name", "")
    if not isinstance(node_name, str):
        raise _reject("graph node name must be a string")
    return PackGraphNode(node_id=node_id, node_type=_require_str(item, "node_type"), name=node_name)


def _parse_graph_nodes(raw_nodes: object) -> tuple[PackGraphNode, ...]:
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise _reject("graph nodes must be a non-empty list")
    nodes: list[PackGraphNode] = []
    node_ids: set[str] = set()
    for item in raw_nodes:
        node = _parse_graph_node(item, node_ids)
        node_ids.add(node.node_id)
        nodes.append(node)
    return tuple(nodes)


def _parse_graph_edges(raw_edges: object, node_ids: set[str]) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw_edges, list):
        raise _reject("graph edges must be a list")
    edges: list[tuple[str, str]] = []
    for item in raw_edges:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(end, str) for end in item)
        ):
            raise _reject("each graph edge must be a [from_node, to_node] pair")
        source, target = item
        for end in (source, target):
            if end not in node_ids:
                raise _reject(f"graph edge endpoint {end!r} is not a node of this graph")
        edges.append((source, target))
    return tuple(edges)


def _parse_graph_payload(payload: object) -> PackGraphDefinition:
    if not isinstance(payload, dict):
        raise _reject("graph payload must be an object")
    name, description, entry_node = _validate_graph_head(payload)
    nodes = _parse_graph_nodes(payload["nodes"])
    node_ids = {node.node_id for node in nodes}
    edges = _parse_graph_edges(payload["edges"], node_ids)
    _validate_entry_node_member(entry_node, node_ids)
    return PackGraphDefinition(
        name=name,
        nodes=nodes,
        edges=edges,
        description=description,
        entry_node=entry_node,
    )


def _validate_graph_head(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    """Keys, name, description, and entry_node type — everything before the
    node/edge structural pass."""
    allowed = {"name", "description", "entry_node", "nodes", "edges"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _reject(f"unknown graph payload keys: {unknown}")
    missing = [key for key in ("name", "nodes", "edges") if key not in payload]
    if missing:
        raise _reject(f"missing graph payload keys: {missing}")
    name = _require_str(payload, "name")
    description = payload.get("description", "")
    if not isinstance(description, str):
        raise _reject("graph description must be a string")
    entry_node = payload.get("entry_node")
    if entry_node is not None and (not isinstance(entry_node, str) or not entry_node.strip()):
        raise _reject("graph entry_node must be a non-empty string when present")
    return name, description, entry_node


def _validate_entry_node_member(entry_node: str | None, node_ids: set[str]) -> None:
    if entry_node is not None and entry_node not in node_ids:
        raise _reject(f"graph entry_node {entry_node!r} is not a node of this graph")


def _freeze(value: Any) -> Any:
    """Recursively freeze a parsed JSON tree into immutable containers.

    The manifest snapshot hands its parsed assets to callers; plain dicts
    and lists inside a persona payload would let a caller mutate a stored
    snapshot in place. Frozen mappings over tuples close every container
    the parser builds — the remaining mutable surface (canonical
    ``RubricDimension`` objects) is closed by :meth:`PackManifest.asset`
    resolving against a pristine re-parse of ``raw``.
    """
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """The inverse of :func:`_freeze`, as fresh plain containers.

    Canonical models validate ``dict``/``list`` fields; every thaw is a
    fresh copy, so an instantiated object never aliases the frozen
    snapshot tree it came from.
    """
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _parse_persona_payload(payload: object) -> PackPersonaDefinition:
    if not isinstance(payload, dict):
        raise _reject("persona payload must be an object")
    allowed = {
        "name",
        "purpose",
        "description",
        "style_guidance",
        "surfaces",
        "defaults",
        "behavior",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _reject(f"unknown persona payload keys: {unknown}")
    if "name" not in payload:
        raise _reject("missing persona payload keys: ['name']")
    name = _require_str(payload, "name")
    _validate_persona_surfaces(payload)
    _validate_persona_objects(payload)
    return PackPersonaDefinition(name=name, payload=_freeze(payload))


def _validate_persona_surfaces(payload: dict[str, Any]) -> None:
    """``surfaces`` is an optional list of non-empty strings."""
    surfaces_raw = payload.get("surfaces", [])
    if not isinstance(surfaces_raw, list) or not all(isinstance(s, str) for s in surfaces_raw):
        raise _reject("persona surfaces must be a list of strings")
    if any(not surface.strip() for surface in surfaces_raw):
        raise _reject("persona surfaces must be non-empty strings")


def _validate_persona_objects(payload: dict[str, Any]) -> None:
    """``defaults``/``behavior`` are optional objects when present."""
    for key in ("defaults", "behavior"):
        if not isinstance(payload.get(key, {}), dict):
            raise _reject(f"persona {key} must be an object")


def _parse_scale(raw: object) -> RubricScale:
    if not isinstance(raw, dict) or not raw:
        raise _reject("rubric dimension scale must be a non-empty object")
    unknown = sorted(set(raw) - {"numeric", "pass_fail"})
    if unknown:
        raise _reject(f"unknown rubric scale keys: {unknown}")
    numeric = None
    pass_fail = None
    if "numeric" in raw:
        block = raw["numeric"]
        if not isinstance(block, dict) or set(block) - {"min_value", "max_value"}:
            raise _reject("numeric scale must have only min_value and max_value")
        numeric = NumericScale(
            min_value=_require_finite(block.get("min_value", 0.0), "numeric min_value"),
            max_value=_require_finite(block.get("max_value", 100.0), "numeric max_value"),
        )
    if "pass_fail" in raw:
        block = raw["pass_fail"]
        if not isinstance(block, dict) or set(block) - {"pass_value", "fail_value"}:
            raise _reject("pass_fail scale must have only pass_value and fail_value")
        pass_fail = PassFailScale(
            pass_value=_require_finite(block.get("pass_value", 1.0), "pass_fail pass_value"),
            fail_value=_require_finite(block.get("fail_value", 0.0), "pass_fail fail_value"),
        )
    return RubricScale(numeric=numeric, pass_fail=pass_fail)


def _parse_rubric_dimension(item: object) -> RubricDimension:
    if not isinstance(item, dict):
        raise _reject("each rubric dimension must be an object")
    allowed_dim = {"id", "name", "weight", "method", "scale", "evidence_required"}
    unknown_dim = sorted(set(item) - allowed_dim)
    if unknown_dim:
        raise _reject(f"unknown rubric dimension keys: {unknown_dim}")
    missing_dim = [key for key in ("id", "name", "weight", "method", "scale") if key not in item]
    if missing_dim:
        raise _reject(f"missing rubric dimension keys: {missing_dim}")
    method = item["method"]
    if not isinstance(method, str) or method not in {m.value for m in ScoringMethod}:
        raise _reject(f"unknown rubric scoring method: {method!r}")
    # bool() coerces any truthy junk ("false" -> True), so require an actual
    # JSON boolean instead of coercing a pack-declared scoring requirement.
    evidence_required = item.get("evidence_required", False)
    if not isinstance(evidence_required, bool):
        raise _reject("rubric evidence_required must be a boolean")
    return RubricDimension(
        id=_require_str(item, "id"),
        name=_require_str(item, "name"),
        weight=_require_finite(item["weight"], "rubric dimension weight"),
        scale=_parse_scale(item["scale"]),
        method=ScoringMethod(method),
        evidence_required=evidence_required,
    )


def _parse_rubric_payload(payload: object) -> PackRubricDefinition:
    if not isinstance(payload, dict):
        raise _reject("rubric payload must be an object")
    name, threshold = _validate_rubric_head(payload)
    dimensions = _parse_rubric_dimensions(payload)
    veto_dimension_ids = _validate_veto_ids(payload)
    return PackRubricDefinition(
        name=name,
        dimensions=dimensions,
        gate_pass_threshold=threshold,
        veto_dimension_ids=veto_dimension_ids,
    )


def _validate_rubric_head(payload: dict[str, Any]) -> tuple[str, float]:
    """Keys, name, and the gate threshold — everything before dimensions."""
    allowed = {"name", "dimensions", "gate_pass_threshold", "veto_dimension_ids"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _reject(f"unknown rubric payload keys: {unknown}")
    missing = [key for key in ("name", "dimensions", "gate_pass_threshold") if key not in payload]
    if missing:
        raise _reject(f"missing rubric payload keys: {missing}")
    name = _require_str(payload, "name")
    threshold = _require_finite(payload["gate_pass_threshold"], "rubric gate_pass_threshold")
    return name, threshold


def _parse_rubric_dimensions(payload: dict[str, Any]) -> tuple[RubricDimension, ...]:
    raw_dimensions = payload["dimensions"]
    if not isinstance(raw_dimensions, list) or not raw_dimensions:
        raise _reject("rubric dimensions must be a non-empty list")
    return tuple(_parse_rubric_dimension(item) for item in raw_dimensions)


def _validate_veto_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    veto_raw = payload.get("veto_dimension_ids", [])
    if not isinstance(veto_raw, list) or not all(isinstance(v, str) for v in veto_raw):
        raise _reject("veto_dimension_ids must be a list of strings")
    return tuple(veto_raw)


_PAYLOAD_KEYS: dict[PackAssetKind, str] = {
    PackAssetKind.GRAPH_TEMPLATE: "graph",
    PackAssetKind.PERSONA: "persona",
    PackAssetKind.RUBRIC: "rubric",
}


def _asset_kind(item: dict[str, Any]) -> PackAssetKind:
    kind_raw = item["kind"]
    if not isinstance(kind_raw, str) or kind_raw not in {k.value for k in PackAssetKind}:
        raise _reject(f"unknown asset kind: {kind_raw!r}")
    return PackAssetKind(kind_raw)


def _asset_payload(
    item: dict[str, Any], kind: PackAssetKind, asset_id: str
) -> PackGraphDefinition | PackPersonaDefinition | PackRubricDefinition:
    """The exactly-one payload block an asset must declare for its kind."""
    payload_key = _PAYLOAD_KEYS[kind]
    payload_keys = set(item) & set(_PAYLOAD_KEYS.values())
    if payload_keys != {payload_key}:
        raise _reject(
            f"asset {asset_id!r} kind {kind.value!r} must declare exactly the "
            f"{payload_key!r} payload (found: {sorted(payload_keys) or 'none'})"
        )
    payload = item[payload_key]
    if kind is PackAssetKind.GRAPH_TEMPLATE:
        return _parse_graph_payload(payload)
    if kind is PackAssetKind.PERSONA:
        return _parse_persona_payload(payload)
    return _parse_rubric_payload(payload)


def _parse_asset(item: object, seen: set[tuple[str, str]]) -> PackAsset:
    if not isinstance(item, dict):
        raise _reject("each asset must be an object")
    unknown = sorted(set(item) - {"asset_id", "version", "kind", *_PAYLOAD_KEYS.values()})
    if unknown:
        raise _reject(f"unknown asset keys: {unknown}")
    for key in ("asset_id", "version", "kind"):
        if key not in item:
            raise _reject(f"missing asset keys: ['{key}']")
    asset_id = _require_str(item, "asset_id")
    if _ASSET_ID_RE.match(asset_id) is None:
        raise _reject(f"malformed asset_id: {asset_id!r}")
    version = _validate_semver(item["version"], "asset version")
    if (asset_id, version) in seen:
        raise _reject(f"duplicate asset identity: {asset_id!r} {version!r}")
    seen.add((asset_id, version))
    kind = _asset_kind(item)
    payload = _asset_payload(item, kind, asset_id)
    return PackAsset(
        asset_id=asset_id,
        version=version,
        kind=kind,
        graph=payload if isinstance(payload, PackGraphDefinition) else None,
        persona=payload if isinstance(payload, PackPersonaDefinition) else None,
        rubric=payload if isinstance(payload, PackRubricDefinition) else None,
    )


# --------------------------------------------------------------------------
# Pack provenance and the manifest snapshot
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PackProvenance:
    """The publisher/version provenance stamped onto instantiated objects."""

    pack_id: str
    publisher: str
    version: str
    manifest_sha256: str

    def as_metadata(self) -> dict[str, str]:
        """The metadata-dict form canonical objects carry."""
        return {
            "pack.id": self.pack_id,
            "pack.publisher": self.publisher,
            "pack.version": self.version,
            "pack.manifest_sha256": self.manifest_sha256,
        }


@dataclass(frozen=True)
class PackManifest:
    """The immutable snapshot of one inspected domain-pack manifest.

    ``raw`` is the exact bytes the operator's decision is about and
    ``source_sha256`` anchors them; a pack identity is
    ``(pack_id, version, source_sha256)`` — a semantic version alone never
    names a pack (the M9-B1 rule, inherited unchanged). The frozen
    dataclasses and tuples keep the outer tree immutable, and every *use*
    of an asset (``asset``/instantiation) is anchored to ``raw`` itself —
    see :meth:`asset`.
    """

    manifest_version: int
    kind: str
    pack_id: str
    name: str
    version: str
    publisher: str
    api_version: str
    capabilities: tuple[str, ...]
    dependencies: tuple[ExtensionDependency, ...]
    assets: tuple[PackAsset, ...]
    source_sha256: str
    raw: bytes = field(repr=False, compare=False)

    def provenance(self) -> PackProvenance:
        """The provenance stamp instantiation puts on created objects."""
        return PackProvenance(
            pack_id=self.pack_id,
            publisher=self.publisher,
            version=self.version,
            manifest_sha256=self.source_sha256,
        )

    def asset(self, asset_id: str, version: str | None = None) -> PackAsset:
        """Resolve one asset by pack-local id, optionally at an exact version.

        Without ``version`` the highest declared version answers — the same
        version-addressing the registry's active-version resolution uses.

        Resolution runs against a pristine re-parse of ``raw``, never the
        stored tree: the outer dataclasses/tuples are frozen and persona
        payload trees are frozen recursively, but the canonical
        ``RubricDimension`` objects inside a rubric asset are mutable (a
        canonical model this contract must not re-freeze). Anchoring every
        use to the immutable bytes means a caller who mutates a stored
        asset cannot make new instantiations diverge from what
        ``source_sha256`` names — the digest stays truthful provenance.
        """
        pristine = inspect_pack_manifest(self.raw)
        candidates = [asset for asset in pristine.assets if asset.asset_id == asset_id]
        if version is not None:
            candidates = [asset for asset in candidates if asset.version == version]
        if not candidates:
            raise PackAssetUnknown(
                f"pack {self.pack_id} {self.version} declares no asset "
                f"{asset_id!r} at version {version!r}"
            )
        return max(candidates, key=lambda asset: _semver_key(asset.version))


def _parse_pack_dependency(item: object, ids: set[str]) -> ExtensionDependency:
    """Validate one dependency entry — the extension manifest's exact shape."""
    if not isinstance(item, dict) or set(item) != {"id", "range"}:
        raise _reject("each dependency must be an object with exactly id and range")
    dep_id, range_spec = item["id"], item["range"]
    if not isinstance(dep_id, str) or _EXTENSION_ID_RE.match(dep_id) is None:
        raise _reject(f"malformed dependency id: {dep_id!r}")
    if not isinstance(range_spec, str) or not range_spec.strip():
        raise _reject(f"malformed dependency range for {dep_id!r}")
    if dep_id in ids:
        raise _reject(f"duplicate dependency: {dep_id!r}")
    ids.add(dep_id)
    return ExtensionDependency(extension_id=dep_id, range_spec=range_spec)


def _parse_dependencies(raw: object) -> tuple[ExtensionDependency, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _reject("dependencies must be a list")
    ids: set[str] = set()
    return tuple(_parse_pack_dependency(item, ids) for item in raw)


def _parse_capabilities(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
        raise _reject("capabilities must be a list of strings")
    seen: set[str] = set()
    for capability in raw:
        if _CAPABILITY_RE.match(capability) is None:
            raise _reject(f"malformed capability token: {capability!r}")
        if capability in seen:
            raise _reject(f"duplicate capability: {capability!r}")
        seen.add(capability)
    return tuple(raw)


# --------------------------------------------------------------------------
# Inspection: bytes → PackManifest, validated as the objects they become
# --------------------------------------------------------------------------


def _canonical_probe_assets(manifest: PackManifest) -> None:
    """Construct (and discard) the canonical object each asset declares.

    This is what makes the pack contract a contract *over canonical objects*:
    an asset payload that canonical validation would refuse fails inspection,
    before any operator decision and long before instantiation. The probe
    workspace/id values are reserved constants no real Workspace is named.
    A canonical refusal is a manifest rejection naming the asset — never a
    raw pydantic error from inside the parser.
    """
    for asset in manifest.assets:
        try:
            if asset.kind is PackAssetKind.GRAPH_TEMPLATE and asset.graph is not None:
                _probe_graph_template(asset.graph)
            elif asset.kind is PackAssetKind.PERSONA and asset.persona is not None:
                _probe_persona(asset.persona)
            elif asset.kind is PackAssetKind.RUBRIC and asset.rubric is not None:
                _probe_rubric(asset.rubric, pack_id=manifest.pack_id)
            else:
                raise _reject(f"asset {asset.asset_id!r} carries no {asset.kind.value} payload")
        except (ValidationError, ValueError) as exc:
            raise _reject(
                f"asset {asset.asset_id!r} payload fails canonical "
                f"{asset.kind.value} validation: {exc}"
            ) from exc


def _probe_graph_template(definition: PackGraphDefinition) -> GraphTemplate:
    """A scratch GraphTemplate: canonical edge/R12-runtime-state validation."""
    nodes = [
        Node(node_id=node.node_id, node_type=node.node_type, name=node.name)
        for node in definition.nodes
    ]
    edges = [
        Edge(edge_id=f"{source}->{target}", from_node=source, to_node=target)
        for source, target in definition.edges
    ]
    metadata: dict[str, Any] = {}
    if definition.entry_node is not None:
        metadata["entry_node"] = definition.entry_node
    return GraphTemplate(
        template_id=_PROBE,
        workspace_id=_PROBE,
        version=1,
        name=definition.name,
        description=definition.description,
        nodes=nodes,
        edges=edges,
        metadata=metadata,
    )


def _persona_constructor_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The pack persona payload as canonical ``Persona`` constructor fields.

    The payload's ``behavior`` key is the pack-facing spelling of the
    canonical model's ``behavior_defaults`` field; everything else maps
    one-to-one. String-keyed by construction (see ``PackPersonaDefinition``).
    The frozen snapshot tree is thawed into fresh plain containers — the
    canonical model validates ``dict``/``list`` fields, and the instantiated
    Persona never aliases the snapshot.
    """
    fields: dict[str, Any] = _thaw(payload)
    fields["behavior_defaults"] = fields.pop("behavior", {})
    return fields


def _probe_persona(definition: PackPersonaDefinition) -> Persona:
    """A scratch Persona: canonical identity/surface validation."""
    # Imported here, not at module level: ``maistro.personas.__init__``
    # eagerly imports the persona expander, which imports
    # ``maistro.agents.recipes`` — a module-level import would make this
    # module unimportable from any context that is still mid-initialization
    # of ``maistro.agents.recipes`` (the runtime anchor chain,
    # ``maistro.runtime`` -> ``maistro.extensions``, is reachable from
    # recipes' own graph import). Canonical validation is unchanged: the
    # real ``Persona`` model gates every probe and instantiation.
    from maistro.personas.model import Persona

    return Persona(
        **{
            **_persona_constructor_fields(definition.payload),
            "id": _PROBE,
            "workspace_id": _PROBE,
        }
    )


def _probe_rubric(definition: PackRubricDefinition, *, pack_id: str) -> RubricSemantic:
    """A scratch RubricSemantic: canonical dimension/gate/provenance validation."""
    return RubricSemantic(
        rubric_id=_PROBE,
        revision=1,
        goal_id=_PROBE,
        goal_revision=1,
        workspace_id=_PROBE,
        project_id=_PROBE,
        dimensions=list(definition.dimensions),
        aggregation=RubricAggregation(veto_dimension_ids=list(definition.veto_dimension_ids)),
        gate=RubricGate(pass_threshold=definition.gate_pass_threshold),
        provenance=RubricProvenance(
            authored_by=_PROBE,
            origin=ProvenanceOrigin.PACK,
            pack_id=pack_id,
        ),
    )


def _parse_pack_identity(
    document: dict[str, Any],
) -> tuple[str, str, str, str, str]:
    """Validate and return (pack_id, name, publisher, version, api_version)."""
    pack_id = _require_str(document, "pack_id")
    segments = pack_id.split(".")
    if len(segments) != 2:
        raise _reject(f"pack_id must be publisher.name (two slug segments), got {pack_id!r}")
    name = _require_str(document, "name")
    publisher = _require_str(document, "publisher")
    if _PUBLISHER_RE.match(publisher) is None:
        raise _reject(f"malformed publisher id: {publisher!r}")
    if segments[0] != publisher:
        raise _reject(
            f"pack_id {pack_id!r} must live under its own publisher namespace {publisher!r}"
        )
    if _PACK_SEGMENT_RE.match(segments[1]) is None:
        raise _reject(f"pack_id name segment must be a slug, got {pack_id!r}")
    version = _validate_semver(document["version"], "version")
    api_version = _validate_semver(document["api_version"], "api_version")
    return pack_id, name, publisher, version, api_version


def inspect_pack_manifest(raw: bytes) -> PackManifest:
    """Parse and validate domain-pack manifest bytes into an immutable snapshot.

    Fails closed on malformed JSON, unknown envelope versions or kinds,
    unexpected keys, malformed identities/semvers/capabilities, duplicate
    assets or dependencies, and any asset payload the canonical
    GraphTemplate/Persona/RubricSemantic models refuse. Never touches a
    payload artifact and never imports anything.
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _reject(f"not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise _reject("top-level document must be an object")
    try:
        return _inspect_document(raw, document)
    except (ValidationError, ValueError) as exc:
        # Canonical-model refusals surface as the typed manifest rejection,
        # with the cause named — never as a raw pydantic error.
        raise _reject(f"payload fails canonical validation: {exc}") from exc


def _validate_manifest_envelope(document: dict[str, Any]) -> None:
    """Envelope keys, supported version, and kind — everything before
    identity/asset parsing, extracted so ``_inspect_document`` stays under
    the complexity floor (same decomposition style as ``_parse_pack_identity``)."""
    required = (
        "manifest_version",
        "kind",
        "pack_id",
        "name",
        "version",
        "publisher",
        "api_version",
        "assets",
    )
    optional = ("capabilities", "dependencies")
    allowed = {*required, *optional}
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise _reject(f"unknown manifest keys: {unknown}")
    missing = [key for key in required if key not in document]
    if missing:
        raise _reject(f"missing manifest keys: {missing}")
    declared_version = document["manifest_version"]
    # `True == 1` and `1.0 == 1` in Python: an equality check alone lets JSON
    # `true`/`1.0` masquerade as the supported integer version, after which the
    # snapshot below silently normalizes the malformed value. Require the type.
    if not isinstance(declared_version, int) or isinstance(declared_version, bool):
        raise _reject(f"manifest_version must be an integer, got {declared_version!r}")
    if declared_version != SUPPORTED_PACK_MANIFEST_VERSION:
        raise _reject(f"unsupported manifest_version: {declared_version!r}")
    if document["kind"] != PACK_MANIFEST_KIND:
        raise _reject(f"unsupported manifest kind: {document['kind']!r}")


def _inspect_document(raw: bytes, document: dict[str, Any]) -> PackManifest:
    _validate_manifest_envelope(document)

    pack_id, name, publisher, version, api_version = _parse_pack_identity(document)

    raw_assets = document["assets"]
    if not isinstance(raw_assets, list) or not raw_assets:
        raise _reject("assets must be a non-empty list")
    seen: set[tuple[str, str]] = set()
    assets = tuple(_parse_asset(item, seen) for item in raw_assets)

    manifest = PackManifest(
        manifest_version=SUPPORTED_PACK_MANIFEST_VERSION,
        kind=PACK_MANIFEST_KIND,
        pack_id=pack_id,
        name=name,
        version=version,
        publisher=publisher,
        api_version=api_version,
        capabilities=_parse_capabilities(document.get("capabilities", [])),
        dependencies=_parse_dependencies(document.get("dependencies")),
        assets=assets,
        source_sha256=sha256_hex(raw),
        raw=raw,
    )
    _canonical_probe_assets(manifest)
    return manifest


# --------------------------------------------------------------------------
# The M9 compatibility machinery, unchanged, over a pack's extension view
# --------------------------------------------------------------------------


def pack_extension_view(manifest: PackManifest) -> ExtensionManifest:
    """Project a pack manifest onto the M9-B2 extension manifest shape.

    Dependency and api-version resolution then run through the one
    compatibility evaluator the platform already has; a pack introduces no
    second resolver. Entry points are empty because a data pack ships
    assets, not code — its only runtime seam remains the governed loader of
    M9-B2, which a pack never grows by declaring assets.
    """
    return ExtensionManifest(
        manifest_version=manifest.manifest_version,
        extension_id=manifest.pack_id,
        name=manifest.name,
        version=manifest.version,
        publisher=manifest.publisher,
        api_version=manifest.api_version,
        permissions=manifest.capabilities,
        entry_points=(),
        dependencies=manifest.dependencies,
        artifact_sha256="0" * 64,
        artifact_size=0,
        source_sha256=manifest.source_sha256,
        raw=manifest.raw,
    )


def evaluate_pack_compatibility(
    manifest: PackManifest, policy: CompatibilityPolicy
) -> CompatibilityReport:
    """Resolve a pack's platform/dependency compatibility via M9 machinery."""
    return evaluate_compatibility(pack_extension_view(manifest), policy)


# --------------------------------------------------------------------------
# Instantiation: pack defaults → canonical objects with pack provenance
# --------------------------------------------------------------------------


def _canonical_id(explicit: str | None, what: str) -> str:
    """The canonical id: caller-supplied, or minted the canonical way.

    A pack-local asset id is never accepted here — canonical identity is
    either the caller's own canonical choice or a fresh canonical mint.
    """
    if explicit is not None:
        if not explicit.strip():
            raise ValueError(f"{what} must be a non-empty string when supplied")
        return explicit
    return uuid.uuid4().hex


def instantiate_graph_asset(
    manifest: PackManifest,
    asset_id: str,
    *,
    workspace_id: str,
    version: str | None = None,
    template_id: str | None = None,
) -> GraphTemplate:
    """Instantiate a pack Graph asset as a canonical Workspace ``GraphTemplate``.

    The template id is minted canonically (or caller-supplied); the pack
    origin rides only in ``metadata`` provenance. The template is
    definition-only: executing it is the canonical executor's job, through
    the ordinary ``GraphTemplate.instantiate`` → Run path.
    """
    if not workspace_id.strip():
        raise ValueError("workspace_id must be a non-empty string")
    asset = manifest.asset(asset_id, version)
    if asset.kind is not PackAssetKind.GRAPH_TEMPLATE or asset.graph is None:
        raise PackAssetUnknown(f"pack asset {asset_id!r} is not a graph asset")
    definition = asset.graph

    template = _probe_graph_template(definition)
    template.metadata["pack"] = manifest.provenance().as_metadata()
    template.metadata["pack.asset_id"] = asset.asset_id
    template.metadata["pack.asset_version"] = asset.version
    return template.model_copy(
        update={
            "template_id": _canonical_id(template_id, "template_id"),
            "workspace_id": workspace_id,
        }
    )


def instantiate_persona_asset(
    manifest: PackManifest,
    asset_id: str,
    *,
    workspace_id: str,
    version: str | None = None,
    persona_id: str | None = None,
) -> Persona:
    """Instantiate a pack Persona asset as a canonical Workspace ``Persona``.

    The Persona id is minted canonically (or caller-supplied) — never the
    pack-local asset id; the pack origin rides in ``source_template_id`` /
    ``source_template_version`` and ``extension_metadata["pack"]``.
    """
    if not workspace_id.strip():
        raise ValueError("workspace_id must be a non-empty string")
    asset = manifest.asset(asset_id, version)
    if asset.kind is not PackAssetKind.PERSONA or asset.persona is None:
        raise PackAssetUnknown(f"pack asset {asset_id!r} is not a persona asset")
    definition = asset.persona

    persona = _probe_persona(definition)
    return persona.model_copy(
        update={
            "id": _canonical_id(persona_id, "persona_id"),
            "workspace_id": workspace_id,
            "source_template_id": f"pack:{manifest.pack_id}:{asset.asset_id}",
            "source_template_version": asset.version,
            "extension_metadata": {"pack": manifest.provenance().as_metadata()},
        }
    )


def instantiate_rubric_asset(
    manifest: PackManifest,
    asset_id: str,
    *,
    goal_id: str,
    goal_revision: int,
    workspace_id: str,
    project_id: str,
    authored_by: str,
    version: str | None = None,
    rubric_id: str | None = None,
    revision: int = 1,
) -> RubricSemantic:
    """Instantiate a pack Rubric asset onto a canonical Goal revision.

    Identity is canonical: ``rubric_id`` is minted (or caller-supplied) and
    the Goal/Workspace/Project scopes are the caller's canonical ones. The
    pack origin rides in ``provenance`` — ``ProvenanceOrigin.PACK`` plus the
    exact source-snapshot identity (pack id/publisher/version, asset
    id/version, manifest digest), so two revisions instantiated from
    different versions of the same pack stay provenance-distinguishable.
    The pack supplied defaults; it does not own the Rubric.
    """
    for field_name, value in (
        ("goal_id", goal_id),
        ("workspace_id", workspace_id),
        ("project_id", project_id),
        ("authored_by", authored_by),
    ):
        if not str(value).strip():
            raise ValueError(f"{field_name} must be a non-empty string")
    asset = manifest.asset(asset_id, version)
    if asset.kind is not PackAssetKind.RUBRIC or asset.rubric is None:
        raise PackAssetUnknown(f"pack asset {asset_id!r} is not a rubric asset")
    definition = asset.rubric

    rubric = _probe_rubric(definition, pack_id=manifest.pack_id)
    pack_provenance = manifest.provenance()
    instantiated = rubric.model_copy(
        update={
            "rubric_id": _canonical_id(rubric_id, "rubric_id"),
            "revision": revision,
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "provenance": RubricProvenance(
                authored_by=authored_by,
                origin=ProvenanceOrigin.PACK,
                pack_id=pack_provenance.pack_id,
                publisher=pack_provenance.publisher,
                pack_version=pack_provenance.version,
                asset_id=asset.asset_id,
                asset_version=asset.version,
                manifest_sha256=pack_provenance.manifest_sha256,
            ),
        }
    )
    # model_copy(update=...) skips validation: caller-supplied identity and
    # scope values must face the canonical model's own constraints (revision
    # and goal_revision are ge=1) before this function returns one.
    try:
        return RubricSemantic.model_validate(instantiated.model_dump())
    except ValidationError as exc:
        raise ValueError(f"instantiated rubric violates the canonical model: {exc}") from exc


# --------------------------------------------------------------------------
# The registry: side-by-side installs, compatibility, disable
# --------------------------------------------------------------------------


class PackState(StrEnum):
    """Durable states of one installed pack version.

    Deliberately two states, not the B2 machine: the pack contract's job is
    the *use gate* (disable stops new use, nothing is deleted). The full
    inspect→authorize→install lifecycle a pack install goes through is the
    M9-B2 service's (#953), and Workspace-scoped activation/config/upgrade
    is M9-F3 (#968) — neither grows here.
    """

    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True)
class PackInstallRecord:
    """One installed pack version: immutable manifest snapshot + use state."""

    manifest: PackManifest
    installed_at: datetime
    state: PackState = PackState.ACTIVE
    #: Why the pack is disabled (empty while active; audited by the caller
    #: that disables, and surfaced verbatim in ``PackDisabledError``).
    note: str = ""

    @property
    def provenance(self) -> PackProvenance:
        return self.manifest.provenance()


class InstallablePackRegistry:
    """One registry of installed out-of-tree packs, keyed by pack identity.

    Multiple packs — from different publishers — install side-by-side;
    multiple versions of one pack install side-by-side and stay individually
    addressable. Every install resolves compatibility through the M9
    machinery against the platform API version and the extensions/packs
    already active here. Disabling a pack stops new instantiation without
    deleting the record, the manifest snapshot, or anything any canonical
    store holds.
    """

    def __init__(
        self,
        *,
        platform_api_version: str,
        active_extensions: Mapping[str, str] | None = None,
    ) -> None:
        self._platform_api_version = platform_api_version
        #: Other extensions active in this scope (capability providers and
        #: friends installed through the M9-B2 service), by extension id.
        self._active_extensions: dict[str, str] = dict(active_extensions or {})
        self._records: dict[tuple[str, str], PackInstallRecord] = {}

    # -- install / state ---------------------------------------------------

    def install(self, raw: bytes) -> PackInstallRecord:
        """Inspect, compatibility-check, and record one pack install.

        Idempotent for identical bytes; a same-(pack_id, version) install
        with different bytes is an identity conflict, never a replacement.
        """
        manifest = inspect_pack_manifest(raw)
        key = (manifest.pack_id, manifest.version)
        existing = self._records.get(key)
        if existing is not None:
            if existing.manifest.source_sha256 != manifest.source_sha256:
                raise PackIdentityConflict(
                    f"{manifest.pack_id} {manifest.version} is already installed "
                    "from different manifest bytes; a version never silently "
                    "becomes different bytes"
                )
            return existing
        if manifest.pack_id in self._active_extensions:
            raise PackIdentityConflict(
                f"{manifest.pack_id} is already active as an extension installed "
                "through the M9-B2 service; one id names one provider, so a pack "
                "install may never shadow it or overwrite its resolved version"
            )

        report = evaluate_pack_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version=self._platform_api_version,
                installed_versions=self._active_versions(),
            ),
        )
        if not report.compatible:
            raise PackIncompatible("; ".join(report.failures))

        record = PackInstallRecord(manifest=manifest, installed_at=datetime.now(UTC))
        self._records[key] = record
        return record

    def disable(
        self, pack_id: str, *, version: str | None = None, note: str = ""
    ) -> PackInstallRecord:
        """Stop new use of one pack version (default: the highest active).

        Deletes nothing: the record and its manifest snapshot stay queryable,
        and objects already instantiated in canonical stores are untouched.
        """
        record = self._require_record(pack_id, version, active_only=True)
        disabled = PackInstallRecord(
            manifest=record.manifest,
            installed_at=record.installed_at,
            state=PackState.DISABLED,
            note=note,
        )
        self._records[(pack_id, record.manifest.version)] = disabled
        return disabled

    def activate(self, pack_id: str, *, version: str | None = None) -> PackInstallRecord:
        """Re-allow new use of one disabled pack version (disable's reversal).

        Named ``activate`` rather than ``enable`` deliberately: the M9
        vocabulary reserves activate for the governed install lifecycle's
        ACTIVE state, and this is exactly its pack-scoped form — a use-gate
        flip on an already-installed record, never a re-install.
        """
        record = self._require_record(pack_id, version, active_only=False)
        if record.state is PackState.ACTIVE:
            return record
        enabled = PackInstallRecord(manifest=record.manifest, installed_at=record.installed_at)
        self._records[(pack_id, record.manifest.version)] = enabled
        return enabled

    # -- lookup ------------------------------------------------------------

    def record(self, pack_id: str, version: str | None = None) -> PackInstallRecord:
        """The install record for a pack version (default: highest installed)."""
        return self._require_record(pack_id, version, active_only=False)

    def records(self) -> tuple[PackInstallRecord, ...]:
        """Every installed record, installed order preserved."""
        return tuple(self._records.values())

    def active_manifest(self, pack_id: str, *, version: str | None = None) -> PackManifest:
        """The manifest new use resolves against; ``PackDisabledError`` if none."""
        record = self._require_record(pack_id, version, active_only=True)
        return record.manifest

    # -- instantiation (gated new use) --------------------------------------

    def instantiate_graph(
        self,
        pack_id: str,
        asset_id: str,
        *,
        workspace_id: str,
        version: str | None = None,
        asset_version: str | None = None,
        template_id: str | None = None,
    ) -> GraphTemplate:
        """Instantiate a pack Graph asset — refused while the pack is disabled."""
        manifest = self.active_manifest(pack_id, version=version)
        return instantiate_graph_asset(
            manifest,
            asset_id,
            workspace_id=workspace_id,
            version=asset_version,
            template_id=template_id,
        )

    def instantiate_persona(
        self,
        pack_id: str,
        asset_id: str,
        *,
        workspace_id: str,
        version: str | None = None,
        asset_version: str | None = None,
        persona_id: str | None = None,
    ) -> Persona:
        """Instantiate a pack Persona asset — refused while disabled."""
        manifest = self.active_manifest(pack_id, version=version)
        return instantiate_persona_asset(
            manifest,
            asset_id,
            workspace_id=workspace_id,
            version=asset_version,
            persona_id=persona_id,
        )

    def instantiate_rubric(
        self,
        pack_id: str,
        asset_id: str,
        *,
        goal_id: str,
        goal_revision: int,
        workspace_id: str,
        project_id: str,
        authored_by: str,
        version: str | None = None,
        asset_version: str | None = None,
        rubric_id: str | None = None,
    ) -> RubricSemantic:
        """Instantiate a pack Rubric asset — refused while disabled."""
        manifest = self.active_manifest(pack_id, version=version)
        return instantiate_rubric_asset(
            manifest,
            asset_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            workspace_id=workspace_id,
            project_id=project_id,
            authored_by=authored_by,
            version=asset_version,
            rubric_id=rubric_id,
        )

    # -- internals ----------------------------------------------------------

    def _active_versions(self) -> dict[str, str]:
        """Every extension/pack id active here, for dependency resolution.

        Several versions of one pack can be active side by side, but the
        compatibility evaluator resolves each dependency id against a single
        version — so it must get the highest active version, the same answer
        ``_require_record`` and the asset lookup give by default. Insertion
        order is not resolution order: whichever version happened to be
        installed last must not make a ``^2.0.0`` dependent fail while an
        active compatible version sits in the registry.
        """
        versions = dict(self._active_extensions)
        highest: dict[str, tuple[tuple[int, int, int], str]] = {}
        for (pack_id, _version), record in self._records.items():
            if record.state is not PackState.ACTIVE:
                continue
            key = _semver_key(record.manifest.version)
            if pack_id not in highest or key > highest[pack_id][0]:
                highest[pack_id] = (key, record.manifest.version)
        for pack_id, (_key, version) in highest.items():
            versions[pack_id] = version
        return versions

    def _require_record(
        self, pack_id: str, version: str | None, *, active_only: bool
    ) -> PackInstallRecord:
        installed = [
            (key, record)
            for key, record in self._records.items()
            if key[0] == pack_id and (version is None or key[1] == version)
        ]
        candidates = [
            entry for entry in installed if not active_only or entry[1].state is PackState.ACTIVE
        ]
        if not candidates:
            _raise_pack_unavailable(pack_id, version, installed)
        # Highest active version wins when the caller does not pin one —
        # deterministic, and version-pinned callers are never surprised.
        _key, record = max(candidates, key=lambda entry: _semver_key(entry[0][1]))
        return record
