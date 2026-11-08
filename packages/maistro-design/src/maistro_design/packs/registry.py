"""The one domain-pack registry (M7-A4, #793).

Every pack loads through this registry — `PackRegistry.builtin()` reads the
in-repo YAML manifests under `maistro_design/packs/manifests/`, one per
`PackId` member. There is no second loading path and no per-pack module:
adding a pack is one enum member plus one manifest, never a new package
identity. Design Studio lists packs through `summaries()`; the uniform
summary shape is the selector contract, deliberately identical for every
pack so no pack can grow product identity through its listing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path as _Path
from typing import Any

import yaml
from pydantic import ValidationError

from maistro_design.packs.graphs import pack_graph_template
from maistro_design.packs.types import DomainPack, PackId, PackSummary

__all__ = [
    "PackManifestError",
    "PackRegistry",
    "PackRegistryError",
    "UnknownPackError",
    "pack_graph_template",
    "parse_manifest",
]


class PackRegistryError(ValueError):
    """Base error for pack registry failures."""


class PackManifestError(PackRegistryError):
    """A built-in manifest is missing or does not satisfy the pack contract."""


class UnknownPackError(PackRegistryError, KeyError):
    """A pack id no manifest in this registry declares."""


_MANIFESTS_PACKAGE = "maistro_design.packs"
_MANIFESTS_DIR = "manifests"


class PackRegistry:
    """One registry of domain packs, keyed by the closed `PackId` enum."""

    def __init__(self, packs: tuple[DomainPack, ...]) -> None:
        by_id: dict[PackId, DomainPack] = {}
        for pack in packs:
            if pack.pack_id in by_id:
                raise PackRegistryError(f"duplicate pack manifest for {pack.pack_id.value!r}")
            by_id[pack.pack_id] = pack
        self._packs = by_id

    @classmethod
    def builtin(cls) -> PackRegistry:
        """Load every shipped pack manifest, one per `PackId` member.

        Iterating the closed enum (not a directory listing) is what makes the
        enum the extension point: a manifest without an enum member cannot be
        loaded, and an enum member without a manifest is a loud
        `PackManifestError` instead of a silently missing pack.
        """
        packs = [cls._load_manifest_text(pack_id) for pack_id in PackId]
        return cls(tuple(packs))

    @staticmethod
    def _load_manifest_text(pack_id: PackId) -> DomainPack:
        path = resources.files(_MANIFESTS_PACKAGE) / _MANIFESTS_DIR / f"{pack_id.value}.yaml"
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PackManifestError(
                f"no manifest shipped for pack {pack_id.value!r}: "
                f"expected {_MANIFESTS_DIR}/{pack_id.value}.yaml"
            ) from exc
        return parse_manifest(pack_id, text)

    def get(self, pack_id: str | PackId) -> DomainPack:
        """Return the pack named by `pack_id` (closed enum) or raise `UnknownPackError`.

        A name outside the closed enum — including a backend name such as
        "canvas" — is an unknown pack, by the same error, so callers cannot
        distinguish "not shipped" from "not a pack".
        """
        try:
            resolved = PackId(pack_id)
        except ValueError as exc:
            raise UnknownPackError(f"{pack_id!r} is not a pack: PackId is a closed enum") from exc
        try:
            return self._packs[resolved]
        except KeyError as exc:
            raise UnknownPackError(f"no pack registered under {resolved.value!r}") from exc

    def list(self) -> tuple[DomainPack, ...]:
        """Every registered pack, ordered by pack id."""
        return tuple(self._packs[pack_id] for pack_id in sorted(PackId) if pack_id in self._packs)

    def summaries(self) -> tuple[PackSummary, ...]:
        """The Design Studio selector payload: one uniform summary per pack."""
        return tuple(pack.to_summary() for pack in self.list())


def parse_manifest(pack_id: PackId, text: str) -> DomainPack:
    """Parse one manifest's YAML into a `DomainPack` — the single parse path.

    `builtin()` reads the in-repo manifests through this; nothing else may
    construct pack objects from manifest text, so a manifest whose pack id is
    outside the closed enum (or whose contract fields are wrong) fails loudly
    here, wherever it was read from.
    """
    try:
        data: dict[str, Any] = yaml.safe_load(text)
        return DomainPack.model_validate(data)
    except (ValidationError, yaml.YAMLError) as exc:
        raise PackManifestError(
            f"manifest for pack {pack_id.value!r} does not satisfy the pack contract: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Legacy/open-cohort pack registry (issue #1619 / #1614). Distinct from the
# M7-A4 YAML PackRegistry above: loads the in-repo JSON catalogs under
# ``packs/catalog/`` (8 packs: book, game, interactive, novel, product,
# small_business, training_program, website) and binds them onto a Goal
# without owning Goal identity. Retained for the open pack cohort scenario
# and ``test_domain_packs.py``.
# ---------------------------------------------------------------------------


LEGACY_REQUIRED_FIELDS = (
    "pack_id",
    "graph_template",
    "rubric_dimensions",
    "backends",
    "artifact_kinds",
    "fence_points",
)

LEGACY_FORBIDDEN_BACKENDS_AS_PACK = frozenset({"canvas", "atelier", "design_run"})


@dataclass(frozen=True, slots=True)
class _LegacyRubricDimension:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class _LegacyDomainPack:
    pack_id: str
    graph_template: str
    rubric_dimensions: tuple[_LegacyRubricDimension, ...]
    backends: tuple[str, ...]
    artifact_kinds: tuple[str, ...]
    fence_points: tuple[str, ...]
    run_identity: str = field(default="canonical")

    def binds_goal(self, goal_id: str) -> dict[str, object]:
        return {
            "goal_id": goal_id,
            "pack_id": self.pack_id,
            "run_identity": self.run_identity,
            "rubric_dimension_ids": [d.id for d in self.rubric_dimensions],
            "graph_template": self.graph_template,
        }


class PackContractError(ValueError):
    """Pack is missing a required contract field or tries to be a product."""


def bundled_pack_dir() -> _Path:
    return _Path(__file__).resolve().parent / "catalog"


def _require_contract_fields(raw: dict[str, object]) -> str:
    """Check the extension rule and return the pack id it declares.

    A pack must declare every required field (notably a graph template and a
    rubric catalog) and must never claim a backend name: `canvas`, `atelier`,
    and `design_run` are backends, not pack ids. All packs share the one
    canonical Run identity.
    """
    missing = [name for name in LEGACY_REQUIRED_FIELDS if not raw.get(name)]
    if missing:
        raise PackContractError(f"pack missing required fields: {missing}")
    pack_id = str(raw["pack_id"])
    if pack_id in LEGACY_FORBIDDEN_BACKENDS_AS_PACK:
        raise PackContractError(f"{pack_id} is a backend, not a pack_id")
    if raw.get("run_identity", "canonical") != "canonical":
        raise PackContractError("packs must share canonical Run identity")
    return pack_id


def _rubric_dimensions(raw: dict[str, object]) -> tuple[_LegacyRubricDimension, ...]:
    """Parse the manifest's rubric catalog; an empty catalog is a contract error."""
    dims_raw = raw["rubric_dimensions"]
    entries = dims_raw if isinstance(dims_raw, list) else []
    dims = tuple(
        _LegacyRubricDimension(id=str(d["id"]), label=str(d["label"]))
        for d in entries
        if isinstance(d, dict)
    )
    if not dims:
        raise PackContractError("pack must declare a rubric catalog")
    return dims


def _as_pack(raw: dict[str, object]) -> _LegacyDomainPack:
    pack_id = _require_contract_fields(raw)
    return _LegacyDomainPack(
        pack_id=pack_id,
        graph_template=str(raw["graph_template"]),
        rubric_dimensions=_rubric_dimensions(raw),
        backends=tuple(str(x) for x in raw["backends"]),  # type: ignore
        artifact_kinds=tuple(str(x) for x in raw["artifact_kinds"]),  # type: ignore
        fence_points=tuple(str(x) for x in raw["fence_points"]),  # type: ignore
        run_identity=str(raw.get("run_identity", "canonical")),
    )


class DomainPackRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, _LegacyDomainPack] = {}

    def register(self, pack: _LegacyDomainPack) -> None:
        self._packs[pack.pack_id] = pack

    def load_file(self, path: _Path) -> _LegacyDomainPack:
        import json as _json

        raw = _json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise PackContractError(f"{path} is not a pack object")
        pack = _as_pack(raw)
        self.register(pack)
        return pack

    def get(self, pack_id: str) -> _LegacyDomainPack:
        try:
            return self._packs[pack_id]
        except KeyError as exc:
            raise PackContractError(f"unknown pack: {pack_id}") from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))

    def bind(self, pack_id: str, goal_id: str) -> dict[str, object]:
        return self.get(pack_id).binds_goal(goal_id)


def load_bundled_packs() -> DomainPackRegistry:
    registry = DomainPackRegistry()
    for path in sorted(bundled_pack_dir().glob("*.json")):
        registry.load_file(path)
    return registry
