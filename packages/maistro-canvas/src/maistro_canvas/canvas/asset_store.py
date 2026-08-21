"""Canvas asset store — persistence for the ADR-039 layer model.

Two implementations:

- ``InMemoryAssetStore``: ephemeral, used by tests. The whole module is
  importable without sqlalchemy.
- ``PostgresAssetStore``: production. Raw SQL via ``sqlalchemy.text()``,
  async, matching the existing canvas ``store.py`` pattern.

Both expose the same shape. Persists:

- ``AssetDefinition`` — registered, named, reusable.
- ``AssetSheet`` — one per asset_id; revision bumps on regenerate.
- ``AssetInstance`` — placement of a definition (inline or registered)
  on a canvas, with scene-graph parent_id + parent_socket.
- ``ChildProfile`` — the personalisation key.
- ``Book`` — natural container for ``WorldStyle`` and ordered
  ``StyleVolume``s.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro_canvas.layers import (
    Anchor,
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    CharacterPose,
    ChildProfile,
    FoundationFootprint,
    LayerKind,
    OcclusionHint,
    PersonalizationSlot,
    RenderStyle,
    Slot,
    StyleVolume,
    Transform,
    WheelAnchors,
    WorldStyle,
    WorldStylePartial,
)
from maistro_canvas.types import (
    AssetDefinitionNotFoundError,
    AssetSheetNotFoundError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ─────────────────────────────────────────────────────────────────────
# Book — the natural container for WorldStyle + StyleVolumes
# ─────────────────────────────────────────────────────────────────────


@dataclass
class Book:
    """A book row. Holds the canonical WorldStyle and an ordered list
    of StyleVolumes that override it for specific page ranges."""

    book_id: str
    title: str
    world_style: WorldStyle
    style_volumes: tuple[StyleVolume, ...] = ()
    profile_id: str | None = None
    org_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ─────────────────────────────────────────────────────────────────────
# SerDes helpers — dataclass <-> JSON-friendly dict
# ─────────────────────────────────────────────────────────────────────


def _ser_socket(s: Any) -> dict[str, Any]:
    return {"name": s.name, "x": s.x, "y": s.y, "role": s.role}


def _deser_socket(d: dict[str, Any]) -> Any:
    from maistro_canvas.layers import Socket

    return Socket(name=d["name"], x=float(d["x"]), y=float(d["y"]), role=d.get("role"))


def _ser_pose_geometry(g: Any) -> dict[str, Any] | None:
    if g is None:
        return None
    if isinstance(g, FoundationFootprint):
        return {"kind": "FoundationFootprint", "polygon": [list(p) for p in g.polygon]}
    if isinstance(g, WheelAnchors):
        return {"kind": "WheelAnchors", "points": [list(p) for p in g.points]}
    if isinstance(g, CharacterPose):
        return {
            "kind": "CharacterPose",
            "bones": {k: list(v) for k, v in g.bones.items()},
            "facial_keypoints": (
                {k: list(v) for k, v in g.facial_keypoints.items()}
                if g.facial_keypoints is not None
                else None
            ),
        }
    msg = f"Unknown pose geometry: {type(g).__name__}"
    raise ValueError(msg)


def _deser_pose_geometry(d: dict[str, Any] | None) -> Any:
    if d is None:
        return None
    kind = d.get("kind")
    if kind == "FoundationFootprint":
        return FoundationFootprint(polygon=tuple(tuple(p) for p in d["polygon"]))
    if kind == "WheelAnchors":
        return WheelAnchors(points=tuple(tuple(p) for p in d["points"]))
    if kind == "CharacterPose":
        return CharacterPose(
            bones={k: tuple(v) for k, v in d["bones"].items()},
            facial_keypoints=(
                {k: tuple(v) for k, v in d["facial_keypoints"].items()}
                if d.get("facial_keypoints")
                else None
            ),
        )
    msg = f"Unknown pose geometry kind: {kind!r}"
    raise ValueError(msg)


def _ser_world_style_partial(w: WorldStylePartial | None) -> dict[str, Any] | None:
    if w is None:
        return None
    return dataclasses.asdict(w)


def _deser_world_style_partial(d: dict[str, Any] | None) -> WorldStylePartial | None:
    if d is None:
        return None
    palette = d.get("palette_anchors")
    return WorldStylePartial(
        era=d.get("era"),
        realism=d.get("realism"),
        architectural_register=d.get("architectural_register"),
        vehicle_register=d.get("vehicle_register"),
        palette_anchors=tuple(palette) if palette is not None else None,
        fauna_realism=d.get("fauna_realism"),
    )


def _ser_world_style(w: WorldStyle) -> dict[str, Any]:
    return {
        "era": w.era,
        "realism": w.realism,
        "architectural_register": w.architectural_register,
        "vehicle_register": w.vehicle_register,
        "palette_anchors": list(w.palette_anchors),
        "fauna_realism": w.fauna_realism,
    }


def _deser_world_style(d: dict[str, Any]) -> WorldStyle:
    return WorldStyle(
        era=d["era"],
        realism=d["realism"],
        architectural_register=d["architectural_register"],
        vehicle_register=d["vehicle_register"],
        palette_anchors=tuple(d["palette_anchors"]),
        fauna_realism=d["fauna_realism"],
    )


def _ser_render_style(r: RenderStyle | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {
        "style_token": r.style_token,
        "palette_override": list(r.palette_override) if r.palette_override is not None else None,
        "line_weight": r.line_weight,
    }


def _deser_render_style(d: dict[str, Any] | None) -> RenderStyle | None:
    if d is None:
        return None
    palette = d.get("palette_override")
    return RenderStyle(
        style_token=d.get("style_token"),
        palette_override=tuple(palette) if palette is not None else None,
        line_weight=d.get("line_weight"),
    )


def _ser_style_volume(sv: StyleVolume) -> dict[str, Any]:
    return {
        "page_range": list(sv.page_range),
        "partial_world_style": _ser_world_style_partial(sv.partial_world_style),
        "partial_render_style": _ser_render_style(sv.partial_render_style),
    }


def _deser_style_volume(d: dict[str, Any]) -> StyleVolume:
    pr = tuple(d["page_range"])
    if len(pr) != 2:
        msg = f"page_range must be a 2-tuple, got {pr!r}"
        raise ValueError(msg)
    return StyleVolume(
        page_range=(int(pr[0]), int(pr[1])),
        partial_world_style=_deser_world_style_partial(d.get("partial_world_style")),
        partial_render_style=_deser_render_style(d.get("partial_render_style")),
    )


def _ser_definition(d: AssetDefinition) -> dict[str, Any]:
    return {
        "asset_id": d.asset_id,
        "kind": d.kind.value,
        "base_prompt": d.base_prompt,
        "asset_sheet": (
            {
                "asset_id": d.asset_sheet.asset_id,
                "refs": list(d.asset_sheet.refs),
                "sheet_image": d.asset_sheet.sheet_image,
                "revision": d.asset_sheet.revision,
                "generation_params": dict(d.asset_sheet.generation_params),
            }
            if d.asset_sheet is not None
            else None
        ),
        "sockets": [_ser_socket(s) for s in d.sockets],
        "skin_set": (
            {k: list(v) for k, v in d.skin_set.items()} if d.skin_set is not None else None
        ),
        "default_world_style": _ser_world_style_partial(d.default_world_style),
        "pose_geometry": _ser_pose_geometry(d.pose_geometry),
    }


def _deser_definition(d: dict[str, Any]) -> AssetDefinition:
    sheet_d = d.get("asset_sheet")
    sheet = (
        AssetSheet(
            asset_id=sheet_d["asset_id"],
            refs=tuple(sheet_d["refs"]),
            sheet_image=sheet_d["sheet_image"],
            revision=int(sheet_d.get("revision", 1)),
            generation_params=dict(sheet_d.get("generation_params", {})),
        )
        if sheet_d is not None
        else None
    )
    skin_set_d = d.get("skin_set")
    skin_set = {k: tuple(v) for k, v in skin_set_d.items()} if skin_set_d is not None else None
    return AssetDefinition(
        asset_id=d["asset_id"],
        kind=LayerKind(d["kind"]),
        base_prompt=d["base_prompt"],
        asset_sheet=sheet,
        sockets=tuple(_deser_socket(s) for s in d.get("sockets", [])),
        skin_set=skin_set,
        default_world_style=_deser_world_style_partial(d.get("default_world_style")),
        pose_geometry=_deser_pose_geometry(d.get("pose_geometry")),
    )


# Canonical fields used to detect "same asset, same definition" for
# idempotent register_definition. Excludes asset_sheet because sheet
# regeneration is independent of definition identity.
_DEFINITION_CANONICAL_KEYS = (
    "kind",
    "base_prompt",
    "sockets",
    "skin_set",
    "default_world_style",
    "pose_geometry",
)


def _definitions_equivalent(a: AssetDefinition, b: AssetDefinition) -> bool:
    sa, sb = _ser_definition(a), _ser_definition(b)
    return all(sa[k] == sb[k] for k in _DEFINITION_CANONICAL_KEYS)


# ─────────────────────────────────────────────────────────────────────
# In-memory store
# ─────────────────────────────────────────────────────────────────────


class InMemoryAssetStore:
    """Ephemeral asset store. Not threadsafe; intended for tests."""

    def __init__(self) -> None:
        self._definitions: dict[str, AssetDefinition] = {}
        self._sheets: dict[str, AssetSheet] = {}
        self._instances: dict[str, AssetInstance] = {}
        self._profiles: dict[str, ChildProfile] = {}
        self._books: dict[str, Book] = {}

    # ── AssetDefinition ─────────────────────────────────────────────

    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition:
        if not defn.asset_id:
            msg = "register_definition requires a non-empty asset_id"
            raise ValueError(msg)
        existing = self._definitions.get(defn.asset_id)
        if existing is not None:
            if _definitions_equivalent(existing, defn):
                return existing  # idempotent no-op
            msg = (
                f"AssetDefinition {defn.asset_id!r} already exists with different canonical fields"
            )
            raise ValueError(msg)
        self._definitions[defn.asset_id] = defn
        return defn

    async def get_definition(self, asset_id: str) -> AssetDefinition | None:
        return self._definitions.get(asset_id)

    async def list_definitions_by_kind(self, kind: str) -> list[AssetDefinition]:
        return [d for d in self._definitions.values() if d.kind.value == kind]

    async def update_definition(self, defn: AssetDefinition) -> AssetDefinition:
        if defn.asset_id not in self._definitions:
            raise AssetDefinitionNotFoundError(defn.asset_id)
        self._definitions[defn.asset_id] = defn
        return defn

    # ── AssetSheet ──────────────────────────────────────────────────

    async def upsert_sheet(self, sheet: AssetSheet) -> AssetSheet:
        self._sheets[sheet.asset_id] = sheet
        # If the parent definition exists, reflect the new sheet on it.
        defn = self._definitions.get(sheet.asset_id)
        if defn is not None:
            self._definitions[sheet.asset_id] = dataclasses.replace(defn, asset_sheet=sheet)
        return sheet

    async def get_sheet(self, asset_id: str) -> AssetSheet | None:
        return self._sheets.get(asset_id)

    async def regenerate_sheet(
        self,
        asset_id: str,
        sheet_image: str,
        refs: tuple[str, ...] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet:
        prev = self._sheets.get(asset_id)
        if prev is None:
            if refs is None:
                raise AssetSheetNotFoundError(asset_id)
            new = AssetSheet(
                asset_id=asset_id,
                refs=refs,
                sheet_image=sheet_image,
                revision=1,
                generation_params=dict(params or {}),
            )
        else:
            new = AssetSheet(
                asset_id=asset_id,
                refs=refs if refs is not None else prev.refs,
                sheet_image=sheet_image,
                revision=prev.revision + 1,
                generation_params=dict(params)
                if params is not None
                else dict(prev.generation_params),
            )
        await self.upsert_sheet(new)
        return new

    # ── AssetInstance ───────────────────────────────────────────────

    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance:
        # Either registry id or inline AssetDefinition; never both, never neither.
        if isinstance(instance.definition, str):
            if not instance.definition:
                msg = "AssetInstance.definition string must be non-empty"
                raise ValueError(msg)
        elif not isinstance(instance.definition, AssetDefinition):
            msg = (
                f"AssetInstance.definition must be str or AssetDefinition, "
                f"got {type(instance.definition).__name__}"
            )
            raise TypeError(msg)
        self._instances[instance.instance_id] = instance
        return instance

    async def get_instance(self, instance_id: str) -> AssetInstance | None:
        return self._instances.get(instance_id)

    async def list_instances(self, canvas_id: str) -> list[AssetInstance]:
        rows = [i for i in self._instances.values() if i.canvas_id == canvas_id]
        # z_index ASC, then insertion order (dicts preserve insertion order on 3.7+).
        rows.sort(key=lambda i: i.z_index)
        return rows

    async def remove_instance(self, instance_id: str) -> None:
        self._instances.pop(instance_id, None)
        # Cascade parent_id references to None on any children.
        for other_id, other in list(self._instances.items()):
            if other.parent_id == instance_id:
                self._instances[other_id] = dataclasses.replace(
                    other, parent_id=None, parent_socket=None
                )

    # ── ChildProfile ────────────────────────────────────────────────

    async def upsert_profile(self, profile: ChildProfile) -> ChildProfile:
        self._profiles[profile.profile_id] = profile
        return profile

    async def get_profile(self, profile_id: str) -> ChildProfile | None:
        return self._profiles.get(profile_id)

    # ── Book ────────────────────────────────────────────────────────

    async def create_book(
        self,
        *,
        book_id: str,
        title: str,
        world_style: WorldStyle,
        style_volumes: tuple[StyleVolume, ...] = (),
        profile_id: str | None = None,
        org_id: str = "",
    ) -> Book:
        if book_id in self._books:
            msg = f"Book {book_id!r} already exists"
            raise ValueError(msg)
        # Enforce StyleVolume.page_range start <= end (ADR-039 EC-10).
        for sv in style_volumes:
            start, end = sv.page_range
            if start > end:
                msg = f"StyleVolume page_range start > end: {sv.page_range!r}"
                raise ValueError(msg)
        book = Book(
            book_id=book_id,
            title=title,
            world_style=world_style,
            style_volumes=style_volumes,
            profile_id=profile_id,
            org_id=org_id,
        )
        self._books[book_id] = book
        return book

    async def get_book(self, book_id: str) -> Book | None:
        return self._books.get(book_id)

    async def update_book(self, book: Book) -> Book:
        if book.book_id not in self._books:
            msg = f"Book {book.book_id!r} not found"
            raise KeyError(msg)
        for sv in book.style_volumes:
            start, end = sv.page_range
            if start > end:
                msg = f"StyleVolume page_range start > end: {sv.page_range!r}"
                raise ValueError(msg)
        self._books[book.book_id] = dataclasses.replace(book, updated_at=datetime.now(UTC))
        return self._books[book.book_id]


# ─────────────────────────────────────────────────────────────────────
# Postgres store — async, raw SQL via sqlalchemy text()
# ─────────────────────────────────────────────────────────────────────


class PostgresAssetStore:
    """Async Postgres store. Same surface as InMemoryAssetStore."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition:
        from sqlalchemy import text

        if not defn.asset_id:
            msg = "register_definition requires a non-empty asset_id"
            raise ValueError(msg)
        existing = await self.get_definition(defn.asset_id)
        if existing is not None:
            if _definitions_equivalent(existing, defn):
                return existing
            msg = (
                f"AssetDefinition {defn.asset_id!r} already exists with different canonical fields"
            )
            raise ValueError(msg)
        ser = _ser_definition(defn)
        await self._session.execute(
            text(
                """
                INSERT INTO asset_definitions
                  (asset_id, kind, base_prompt, sockets, skin_set,
                   default_world_style, pose_geometry)
                VALUES
                  (:asset_id, :kind, :base_prompt, CAST(:sockets AS JSONB),
                   CAST(:skin_set AS JSONB),
                   CAST(:default_world_style AS JSONB),
                   CAST(:pose_geometry AS JSONB))
                """
            ),
            {
                "asset_id": ser["asset_id"],
                "kind": ser["kind"],
                "base_prompt": ser["base_prompt"],
                "sockets": json.dumps(ser["sockets"]),
                "skin_set": json.dumps(ser["skin_set"]),
                "default_world_style": json.dumps(ser["default_world_style"]),
                "pose_geometry": json.dumps(ser["pose_geometry"]),
            },
        )
        # Sheet, if any, persists separately.
        if defn.asset_sheet is not None:
            await self.upsert_sheet(defn.asset_sheet)
        return defn

    async def get_definition(self, asset_id: str) -> AssetDefinition | None:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT * FROM asset_definitions WHERE asset_id = :a"),
            {"a": asset_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        defn = _deser_definition(_row_to_definition_dict(row))
        sheet = await self.get_sheet(asset_id)
        if sheet is not None:
            defn = dataclasses.replace(defn, asset_sheet=sheet)
        return defn

    async def list_definitions_by_kind(self, kind: str) -> list[AssetDefinition]:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT * FROM asset_definitions WHERE kind = :k ORDER BY asset_id"),
            {"k": kind},
        )
        out: list[AssetDefinition] = []
        for row in result.mappings().all():
            d = _deser_definition(_row_to_definition_dict(row))
            sheet = await self.get_sheet(d.asset_id)
            if sheet is not None:
                d = dataclasses.replace(d, asset_sheet=sheet)
            out.append(d)
        return out

    async def update_definition(self, defn: AssetDefinition) -> AssetDefinition:
        from sqlalchemy import text

        ser = _ser_definition(defn)
        # Existence check first; UPDATE doesn't expose a typed rowcount.
        existing = await self._session.execute(
            text("SELECT 1 FROM asset_definitions WHERE asset_id = :a"),
            {"a": defn.asset_id},
        )
        if existing.first() is None:
            raise AssetDefinitionNotFoundError(defn.asset_id)
        await self._session.execute(
            text(
                """
                UPDATE asset_definitions SET
                  kind = :kind,
                  base_prompt = :base_prompt,
                  sockets = CAST(:sockets AS JSONB),
                  skin_set = CAST(:skin_set AS JSONB),
                  default_world_style = CAST(:default_world_style AS JSONB),
                  pose_geometry = CAST(:pose_geometry AS JSONB),
                  updated_at = now()
                WHERE asset_id = :asset_id
                """
            ),
            {
                "asset_id": ser["asset_id"],
                "kind": ser["kind"],
                "base_prompt": ser["base_prompt"],
                "sockets": json.dumps(ser["sockets"]),
                "skin_set": json.dumps(ser["skin_set"]),
                "default_world_style": json.dumps(ser["default_world_style"]),
                "pose_geometry": json.dumps(ser["pose_geometry"]),
            },
        )
        if defn.asset_sheet is not None:
            await self.upsert_sheet(defn.asset_sheet)
        return defn

    async def upsert_sheet(self, sheet: AssetSheet) -> AssetSheet:
        from sqlalchemy import text

        await self._session.execute(
            text(
                """
                INSERT INTO asset_sheets
                  (asset_id, refs, sheet_image, revision, generation_params)
                VALUES
                  (:asset_id, CAST(:refs AS JSONB), :sheet_image, :revision,
                   CAST(:params AS JSONB))
                ON CONFLICT (asset_id) DO UPDATE SET
                  refs = EXCLUDED.refs,
                  sheet_image = EXCLUDED.sheet_image,
                  revision = EXCLUDED.revision,
                  generation_params = EXCLUDED.generation_params,
                  updated_at = now()
                """
            ),
            {
                "asset_id": sheet.asset_id,
                "refs": json.dumps(list(sheet.refs)),
                "sheet_image": sheet.sheet_image,
                "revision": sheet.revision,
                "params": json.dumps(dict(sheet.generation_params)),
            },
        )
        return sheet

    async def get_sheet(self, asset_id: str) -> AssetSheet | None:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT * FROM asset_sheets WHERE asset_id = :a"),
            {"a": asset_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return AssetSheet(
            asset_id=str(row["asset_id"]),
            refs=tuple(_load_json(row["refs"], default=[])),
            sheet_image=str(row["sheet_image"]),
            revision=int(row["revision"]),
            generation_params=dict(_load_json(row["generation_params"], default={})),
        )

    async def regenerate_sheet(
        self,
        asset_id: str,
        sheet_image: str,
        refs: tuple[str, ...] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet:
        from sqlalchemy import text

        # SELECT FOR UPDATE then INSERT/UPDATE atomically — concurrent
        # regenerates serialise on the row lock and produce strictly
        # increasing revisions.
        result = await self._session.execute(
            text("SELECT * FROM asset_sheets WHERE asset_id = :a FOR UPDATE"),
            {"a": asset_id},
        )
        row = result.mappings().first()
        if row is None:
            if refs is None:
                raise AssetSheetNotFoundError(asset_id)
            new = AssetSheet(
                asset_id=asset_id,
                refs=refs,
                sheet_image=sheet_image,
                revision=1,
                generation_params=dict(params or {}),
            )
        else:
            prev_refs = tuple(_load_json(row["refs"], default=[]))
            prev_params = dict(_load_json(row["generation_params"], default={}))
            new = AssetSheet(
                asset_id=asset_id,
                refs=refs if refs is not None else prev_refs,
                sheet_image=sheet_image,
                revision=int(row["revision"]) + 1,
                generation_params=dict(params) if params is not None else prev_params,
            )
        await self.upsert_sheet(new)
        return new

    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance:
        from sqlalchemy import text

        if isinstance(instance.definition, str):
            definition_id: str | None = instance.definition
            inline_definition: str | None = None
            if not definition_id:
                msg = "AssetInstance.definition string must be non-empty"
                raise ValueError(msg)
        elif isinstance(instance.definition, AssetDefinition):
            definition_id = None
            inline_definition = json.dumps(_ser_definition(instance.definition))
        else:
            msg = (
                f"AssetInstance.definition must be str or AssetDefinition, "
                f"got {type(instance.definition).__name__}"
            )
            raise TypeError(msg)

        await self._session.execute(
            text(
                """
                INSERT INTO asset_instances
                  (instance_id, canvas_id, definition_id, inline_definition,
                   parent_id, parent_socket, transform, slot, anchor,
                   occlusion, personalization, skin_binding, prompt_nudge,
                   visible, locked, history, z_index)
                VALUES
                  (:instance_id, :canvas_id, :definition_id,
                   CAST(:inline_definition AS JSONB),
                   :parent_id, :parent_socket,
                   CAST(:transform AS JSONB), CAST(:slot AS JSONB), :anchor,
                   CAST(:occlusion AS JSONB), CAST(:personalization AS JSONB),
                   CAST(:skin_binding AS JSONB), :prompt_nudge,
                   :visible, :locked, CAST(:history AS JSONB), :z_index)
                ON CONFLICT (instance_id) DO UPDATE SET
                  canvas_id = EXCLUDED.canvas_id,
                  definition_id = EXCLUDED.definition_id,
                  inline_definition = EXCLUDED.inline_definition,
                  parent_id = EXCLUDED.parent_id,
                  parent_socket = EXCLUDED.parent_socket,
                  transform = EXCLUDED.transform,
                  slot = EXCLUDED.slot,
                  anchor = EXCLUDED.anchor,
                  occlusion = EXCLUDED.occlusion,
                  personalization = EXCLUDED.personalization,
                  skin_binding = EXCLUDED.skin_binding,
                  prompt_nudge = EXCLUDED.prompt_nudge,
                  visible = EXCLUDED.visible,
                  locked = EXCLUDED.locked,
                  history = EXCLUDED.history,
                  z_index = EXCLUDED.z_index,
                  updated_at = now()
                """
            ),
            {
                "instance_id": instance.instance_id,
                "canvas_id": instance.canvas_id,
                "definition_id": definition_id,
                "inline_definition": inline_definition,
                "parent_id": instance.parent_id,
                "parent_socket": instance.parent_socket,
                "transform": json.dumps(dataclasses.asdict(instance.transform)),
                "slot": (
                    json.dumps(dataclasses.asdict(instance.slot))
                    if instance.slot is not None
                    else None
                ),
                "anchor": instance.anchor.value if instance.anchor is not None else None,
                "occlusion": json.dumps(
                    {
                        "in_front_of": list(instance.occlusion.in_front_of),
                        "behind": list(instance.occlusion.behind),
                    }
                ),
                "personalization": (
                    json.dumps(
                        {
                            "kind": instance.personalization.kind,
                            "binding": instance.personalization.binding,
                        }
                    )
                    if instance.personalization is not None
                    else None
                ),
                "skin_binding": (
                    json.dumps(instance.skin_binding) if instance.skin_binding is not None else None
                ),
                "prompt_nudge": instance.prompt_nudge,
                "visible": instance.visible,
                "locked": instance.locked,
                "history": json.dumps(list(instance.history)),
                "z_index": instance.z_index,
            },
        )
        return instance

    async def get_instance(self, instance_id: str) -> AssetInstance | None:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT * FROM asset_instances WHERE instance_id = :i"),
            {"i": instance_id},
        )
        row = result.mappings().first()
        return _coerce_instance(row) if row is not None else None

    async def list_instances(self, canvas_id: str) -> list[AssetInstance]:
        from sqlalchemy import text

        result = await self._session.execute(
            text(
                "SELECT * FROM asset_instances WHERE canvas_id = :c "
                "ORDER BY z_index ASC, created_at ASC"
            ),
            {"c": canvas_id},
        )
        return [_coerce_instance(row) for row in result.mappings().all()]

    async def remove_instance(self, instance_id: str) -> None:
        from sqlalchemy import text

        await self._session.execute(
            text("DELETE FROM asset_instances WHERE instance_id = :i"),
            {"i": instance_id},
        )

    async def upsert_profile(self, profile: ChildProfile) -> ChildProfile:
        from sqlalchemy import text

        await self._session.execute(
            text(
                """
                INSERT INTO child_profiles
                  (profile_id, name, pronouns, likeness_refs, accommodations,
                   age_range, reading_level)
                VALUES
                  (:profile_id, :name, :pronouns,
                   CAST(:likeness_refs AS JSONB),
                   CAST(:accommodations AS JSONB),
                   :age_range, :reading_level)
                ON CONFLICT (profile_id) DO UPDATE SET
                  name = EXCLUDED.name,
                  pronouns = EXCLUDED.pronouns,
                  likeness_refs = EXCLUDED.likeness_refs,
                  accommodations = EXCLUDED.accommodations,
                  age_range = EXCLUDED.age_range,
                  reading_level = EXCLUDED.reading_level,
                  updated_at = now()
                """
            ),
            {
                "profile_id": profile.profile_id,
                "name": profile.name,
                "pronouns": profile.pronouns,
                "likeness_refs": json.dumps(list(profile.likeness_refs)),
                "accommodations": json.dumps(list(profile.accommodations)),
                "age_range": profile.age_range,
                "reading_level": profile.reading_level,
            },
        )
        return profile

    async def get_profile(self, profile_id: str) -> ChildProfile | None:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT * FROM child_profiles WHERE profile_id = :p"),
            {"p": profile_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return ChildProfile(
            profile_id=str(row["profile_id"]),
            name=str(row["name"]),
            pronouns=row["pronouns"],
            likeness_refs=tuple(_load_json(row["likeness_refs"], default=[])),
            accommodations=tuple(_load_json(row["accommodations"], default=[])),
            age_range=row["age_range"],
            reading_level=row["reading_level"],
        )

    async def create_book(
        self,
        *,
        book_id: str,
        title: str,
        world_style: WorldStyle,
        style_volumes: tuple[StyleVolume, ...] = (),
        profile_id: str | None = None,
        org_id: str = "",
    ) -> Book:
        from sqlalchemy import text

        for sv in style_volumes:
            start, end = sv.page_range
            if start > end:
                msg = f"StyleVolume page_range start > end: {sv.page_range!r}"
                raise ValueError(msg)
        await self._session.execute(
            text(
                """
                INSERT INTO books
                  (book_id, title, world_style, style_volumes, profile_id, org_id)
                VALUES
                  (:book_id, :title, CAST(:world_style AS JSONB),
                   CAST(:style_volumes AS JSONB), :profile_id, :org_id)
                """
            ),
            {
                "book_id": book_id,
                "title": title,
                "world_style": json.dumps(_ser_world_style(world_style)),
                "style_volumes": json.dumps([_ser_style_volume(sv) for sv in style_volumes]),
                "profile_id": profile_id,
                "org_id": org_id,
            },
        )
        return Book(
            book_id=book_id,
            title=title,
            world_style=world_style,
            style_volumes=style_volumes,
            profile_id=profile_id,
            org_id=org_id,
        )

    async def get_book(self, book_id: str) -> Book | None:
        from sqlalchemy import text

        result = await self._session.execute(
            text("SELECT * FROM books WHERE book_id = :b"),
            {"b": book_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return Book(
            book_id=str(row["book_id"]),
            title=str(row["title"]),
            world_style=_deser_world_style(_load_json(row["world_style"], default={})),
            style_volumes=tuple(
                _deser_style_volume(sv) for sv in _load_json(row["style_volumes"], default=[])
            ),
            profile_id=row["profile_id"],
            org_id=str(row.get("org_id", "")),
        )

    async def update_book(self, book: Book) -> Book:
        from sqlalchemy import text

        for sv in book.style_volumes:
            start, end = sv.page_range
            if start > end:
                msg = f"StyleVolume page_range start > end: {sv.page_range!r}"
                raise ValueError(msg)
        existing = await self._session.execute(
            text("SELECT 1 FROM books WHERE book_id = :b"),
            {"b": book.book_id},
        )
        if existing.first() is None:
            msg = f"Book {book.book_id!r} not found"
            raise KeyError(msg)
        await self._session.execute(
            text(
                """
                UPDATE books SET
                  title = :title,
                  world_style = CAST(:world_style AS JSONB),
                  style_volumes = CAST(:style_volumes AS JSONB),
                  profile_id = :profile_id,
                  updated_at = now()
                WHERE book_id = :book_id
                """
            ),
            {
                "book_id": book.book_id,
                "title": book.title,
                "world_style": json.dumps(_ser_world_style(book.world_style)),
                "style_volumes": json.dumps([_ser_style_volume(sv) for sv in book.style_volumes]),
                "profile_id": book.profile_id,
            },
        )
        return dataclasses.replace(book, updated_at=datetime.now(UTC))


# ─────────────────────────────────────────────────────────────────────
# Postgres row coercion helpers
# ─────────────────────────────────────────────────────────────────────


def _load_json(value: Any, *, default: Any = None) -> Any:
    """Postgres JSONB columns may arrive as dict/list (pg2) or str
    depending on driver; normalise to native Python."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_definition_dict(row: Any) -> dict[str, Any]:
    return {
        "asset_id": str(row["asset_id"]),
        "kind": str(row["kind"]),
        "base_prompt": str(row["base_prompt"]),
        "asset_sheet": None,  # joined separately
        "sockets": _load_json(row["sockets"], default=[]),
        "skin_set": _load_json(row["skin_set"], default=None),
        "default_world_style": _load_json(row["default_world_style"], default=None),
        "pose_geometry": _load_json(row["pose_geometry"], default=None),
    }


def _coerce_instance(row: Any) -> AssetInstance:
    inline = _load_json(row["inline_definition"], default=None)
    if inline is not None:
        definition: AssetDefinition | str = _deser_definition(inline)
    else:
        definition = str(row["definition_id"])
    transform_d = _load_json(row["transform"], default={})
    slot_d = _load_json(row["slot"], default=None)
    occl = _load_json(row["occlusion"], default={"in_front_of": [], "behind": []})
    pers_d = _load_json(row["personalization"], default=None)
    skin_d = _load_json(row["skin_binding"], default=None)
    return AssetInstance(
        instance_id=str(row["instance_id"]),
        canvas_id=str(row["canvas_id"]),
        definition=definition,
        parent_id=row["parent_id"],
        parent_socket=row["parent_socket"],
        transform=Transform(
            tx=float(transform_d.get("tx", 0.0)),
            ty=float(transform_d.get("ty", 0.0)),
            sx=float(transform_d.get("sx", 1.0)),
            sy=float(transform_d.get("sy", 1.0)),
            rotation=float(transform_d.get("rotation", 0.0)),
        ),
        slot=(
            Slot(
                x=float(slot_d["x"]),
                y=float(slot_d["y"]),
                w=float(slot_d["w"]),
                h=float(slot_d["h"]),
            )
            if slot_d is not None
            else None
        ),
        anchor=Anchor(row["anchor"]) if row["anchor"] is not None else None,
        occlusion=OcclusionHint(
            in_front_of=tuple(occl.get("in_front_of", [])),
            behind=tuple(occl.get("behind", [])),
        ),
        personalization=(
            PersonalizationSlot(kind=pers_d["kind"], binding=pers_d["binding"])
            if pers_d is not None
            else None
        ),
        skin_binding=dict(skin_d) if skin_d is not None else None,
        prompt_nudge=row["prompt_nudge"],
        visible=bool(row["visible"]),
        locked=bool(row["locked"]),
        history=tuple(_load_json(row["history"], default=[])),
        z_index=int(row["z_index"]),
    )


__all__ = [
    "Book",
    "InMemoryAssetStore",
    "PostgresAssetStore",
]
