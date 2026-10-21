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

from importlib import resources
from typing import Any

import yaml
from pydantic import ValidationError

from maistro_design.packs.graphs import pack_graph_template
from maistro_design.packs.types import DomainPack, ExecuteBackend, PackId, PackSummary

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


def assert_no_pack_is_named_after_a_backend(packs: tuple[DomainPack, ...]) -> None:
    """Contract guard: backend names are binding names, never pack identities.

    Kept as an explicit, callable check (rather than only a model validator)
    so the registry-level invariant is assertable independently of how a
    `DomainPack` was constructed.
    """
    backend_names = {backend.value for backend in ExecuteBackend}
    for pack in packs:
        if pack.pack_id.value in backend_names:
            raise PackRegistryError(
                f"pack_id {pack.pack_id.value!r} collides with an execute backend name"
            )
