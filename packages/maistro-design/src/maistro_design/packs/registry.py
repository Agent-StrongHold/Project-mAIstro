"""One in-repo pack registry. Adding a pack must not add a package."""

from __future__ import annotations

import json
from pathlib import Path

from maistro_design.packs.types import DomainPack, RubricDimension

REQUIRED_FIELDS = (
    "pack_id",
    "graph_template",
    "rubric_dimensions",
    "backends",
    "artifact_kinds",
    "fence_points",
)

FORBIDDEN_BACKENDS_AS_PACK = frozenset({"canvas", "atelier", "design_run"})


class PackContractError(ValueError):
    """Pack is missing a required contract field or tries to be a product."""


def bundled_pack_dir() -> Path:
    return Path(__file__).resolve().parent / "catalog"


def _as_pack(raw: dict[str, object]) -> DomainPack:
    missing = [name for name in REQUIRED_FIELDS if not raw.get(name)]
    if missing:
        raise PackContractError(f"pack missing required fields: {missing}")
    pack_id = str(raw["pack_id"])
    if pack_id in FORBIDDEN_BACKENDS_AS_PACK:
        raise PackContractError(f"{pack_id} is a backend, not a pack_id")
    if raw.get("run_identity", "canonical") != "canonical":
        raise PackContractError("packs must share canonical Run identity")
    dims_raw = raw["rubric_dimensions"]
    if not isinstance(dims_raw, list) or not dims_raw:
        raise PackContractError("pack must declare a rubric catalog")
    dims = tuple(
        RubricDimension(id=str(d["id"]), label=str(d["label"]))
        for d in dims_raw
        if isinstance(d, dict)
    )
    if not dims:
        raise PackContractError("pack must declare a rubric catalog")
    return DomainPack(
        pack_id=pack_id,
        graph_template=str(raw["graph_template"]),
        rubric_dimensions=dims,
        backends=tuple(str(x) for x in raw["backends"]),  # type: ignore[arg-type]
        artifact_kinds=tuple(str(x) for x in raw["artifact_kinds"]),  # type: ignore[arg-type]
        fence_points=tuple(str(x) for x in raw["fence_points"]),  # type: ignore[arg-type]
    )


class DomainPackRegistry:
    def __init__(self) -> None:
        self._packs: dict[str, DomainPack] = {}

    def register(self, pack: DomainPack) -> None:
        self._packs[pack.pack_id] = pack

    def load_file(self, path: Path) -> DomainPack:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise PackContractError(f"{path} is not a pack object")
        pack = _as_pack(raw)
        self.register(pack)
        return pack

    def get(self, pack_id: str) -> DomainPack:
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
