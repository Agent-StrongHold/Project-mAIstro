"""Boundary + behavioral tests for the in-memory asset store (ADR-040).

Covers the contracts called out in ADR-040 §"Boundary contracts" and
§"Behavioral contracts". Postgres-backed contracts identical-shape but
require a live DB; tested separately.
"""

from __future__ import annotations

import pytest

from maistro_canvas.canvas.asset_store import InMemoryAssetStore
from maistro_canvas.layers import (
    Anchor,
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    CharacterPose,
    ChildProfile,
    LayerKind,
    OcclusionHint,
    PersonalizationSlot,
    Socket,
    StyleVolume,
    Transform,
    WorldStyle,
    WorldStylePartial,
)
from maistro_canvas.types import (
    AssetDefinitionNotFoundError,
    AssetSheetNotFoundError,
)


def _world_style() -> WorldStyle:
    return WorldStyle(
        era="modern",
        realism="watercolor",
        architectural_register="cottage",
        vehicle_register="1970s-pickup",
        palette_anchors=("sage", "cream"),
        fauna_realism="cute",
    )


# ─────────────────────────────────────────────────────────────────────
# AssetDefinition
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_definition_persists_and_returns():
    store = InMemoryAssetStore()
    defn = AssetDefinition(
        asset_id="farmhouse_red_v1",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small red farmhouse",
        sockets=(Socket(name="door", x=0.5, y=0.8),),
    )
    out = await store.register_definition(defn)
    assert out is defn
    assert await store.get_definition("farmhouse_red_v1") is defn


@pytest.mark.asyncio
async def test_register_definition_idempotent_on_identical_canonical_fields():
    store = InMemoryAssetStore()
    a = AssetDefinition(
        asset_id="farmhouse_red_v1",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small red farmhouse",
        sockets=(Socket(name="door", x=0.5, y=0.8),),
    )
    b = AssetDefinition(
        asset_id="farmhouse_red_v1",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small red farmhouse",
        sockets=(Socket(name="door", x=0.5, y=0.8),),
    )
    await store.register_definition(a)
    out = await store.register_definition(b)
    assert out is a  # idempotent: original returned, no overwrite


@pytest.mark.asyncio
async def test_register_definition_rejects_diverging_canonical_fields():
    store = InMemoryAssetStore()
    a = AssetDefinition(
        asset_id="farmhouse_red_v1",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small red farmhouse",
    )
    b = AssetDefinition(
        asset_id="farmhouse_red_v1",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small BLUE farmhouse",  # different canonical field
    )
    await store.register_definition(a)
    with pytest.raises(ValueError, match="already exists"):
        await store.register_definition(b)


@pytest.mark.asyncio
async def test_register_definition_requires_asset_id():
    store = InMemoryAssetStore()
    bad = AssetDefinition(asset_id="", kind=LayerKind.STRUCTURE, base_prompt="x")
    with pytest.raises(ValueError, match="asset_id"):
        await store.register_definition(bad)


@pytest.mark.asyncio
async def test_list_definitions_by_kind_filters():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(asset_id="house_a", kind=LayerKind.STRUCTURE, base_prompt="a")
    )
    await store.register_definition(
        AssetDefinition(asset_id="car_a", kind=LayerKind.VEHICLE, base_prompt="a")
    )
    await store.register_definition(
        AssetDefinition(asset_id="house_b", kind=LayerKind.STRUCTURE, base_prompt="b")
    )
    structures = await store.list_definitions_by_kind("structure")
    ids = {d.asset_id for d in structures}
    assert ids == {"house_a", "house_b"}


@pytest.mark.asyncio
async def test_update_definition_raises_when_missing():
    store = InMemoryAssetStore()
    with pytest.raises(AssetDefinitionNotFoundError):
        await store.update_definition(
            AssetDefinition(asset_id="ghost", kind=LayerKind.PROP, base_prompt="x")
        )


# ─────────────────────────────────────────────────────────────────────
# AssetSheet
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_sheet_starts_at_one_when_no_prior():
    store = InMemoryAssetStore()
    sheet = await store.regenerate_sheet(
        "asset_x", "/tmp/sheet_v1.png", refs=("/r1.png", "/r2.png", "/r3.png")
    )
    assert sheet.revision == 1
    assert sheet.sheet_image == "/tmp/sheet_v1.png"


@pytest.mark.asyncio
async def test_regenerate_sheet_is_monotonic():
    store = InMemoryAssetStore()
    s1 = await store.regenerate_sheet(
        "asset_x", "/tmp/sheet_v1.png", refs=("/r1.png", "/r2.png", "/r3.png")
    )
    s2 = await store.regenerate_sheet("asset_x", "/tmp/sheet_v2.png")
    s3 = await store.regenerate_sheet("asset_x", "/tmp/sheet_v3.png")
    assert s1.revision == 1
    assert s2.revision == 2
    assert s3.revision == 3
    assert s3.sheet_image == "/tmp/sheet_v3.png"


@pytest.mark.asyncio
async def test_regenerate_sheet_without_prior_or_refs_raises():
    store = InMemoryAssetStore()
    with pytest.raises(AssetSheetNotFoundError):
        await store.regenerate_sheet("missing_asset", "/tmp/x.png")


@pytest.mark.asyncio
async def test_upsert_sheet_reflected_on_definition():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(asset_id="char_proto", kind=LayerKind.CHARACTER, base_prompt="x")
    )
    sheet = AssetSheet(
        asset_id="char_proto",
        refs=("/a.png", "/b.png", "/c.png"),
        sheet_image="/sheet.png",
    )
    await store.upsert_sheet(sheet)
    defn = await store.get_definition("char_proto")
    assert defn is not None
    assert defn.asset_sheet is not None
    assert defn.asset_sheet.sheet_image == "/sheet.png"


# ─────────────────────────────────────────────────────────────────────
# AssetInstance
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_instance_with_registry_id():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(asset_id="farmhouse", kind=LayerKind.STRUCTURE, base_prompt="x")
    )
    instance = AssetInstance(
        instance_id="i_1",
        canvas_id="c_1",
        definition="farmhouse",
        anchor=Anchor.GROUND_CONTACT,
    )
    await store.upsert_instance(instance)
    out = await store.get_instance("i_1")
    assert out is not None
    assert out.definition == "farmhouse"


@pytest.mark.asyncio
async def test_upsert_instance_with_inline_definition():
    store = InMemoryAssetStore()
    inline = AssetDefinition(asset_id="", kind=LayerKind.FX, base_prompt="a wispy cloud")
    instance = AssetInstance(
        instance_id="cloud_1", canvas_id="c_1", definition=inline, anchor=Anchor.FLOATING
    )
    await store.upsert_instance(instance)
    out = await store.get_instance("cloud_1")
    assert out is not None
    assert isinstance(out.definition, AssetDefinition)
    assert out.definition.kind is LayerKind.FX


@pytest.mark.asyncio
async def test_upsert_instance_rejects_invalid_definition_type():
    store = InMemoryAssetStore()
    instance = AssetInstance(instance_id="i_1", canvas_id="c_1", definition=123)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await store.upsert_instance(instance)


@pytest.mark.asyncio
async def test_upsert_instance_rejects_empty_string_definition():
    store = InMemoryAssetStore()
    instance = AssetInstance(instance_id="i_1", canvas_id="c_1", definition="")
    with pytest.raises(ValueError, match="non-empty"):
        await store.upsert_instance(instance)


@pytest.mark.asyncio
async def test_list_instances_orders_by_z_index_then_insertion():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(asset_id="a", kind=LayerKind.STRUCTURE, base_prompt="x")
    )
    # Insert in order C, A, B; z 5, 0, 0.
    await store.upsert_instance(
        AssetInstance(instance_id="C", canvas_id="c_1", definition="a", z_index=5)
    )
    await store.upsert_instance(
        AssetInstance(instance_id="A", canvas_id="c_1", definition="a", z_index=0)
    )
    await store.upsert_instance(
        AssetInstance(instance_id="B", canvas_id="c_1", definition="a", z_index=0)
    )
    out = await store.list_instances("c_1")
    assert [i.instance_id for i in out] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_list_instances_scopes_to_canvas():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(asset_id="a", kind=LayerKind.STRUCTURE, base_prompt="x")
    )
    await store.upsert_instance(AssetInstance(instance_id="i1", canvas_id="c_1", definition="a"))
    await store.upsert_instance(AssetInstance(instance_id="i2", canvas_id="c_2", definition="a"))
    only_c1 = await store.list_instances("c_1")
    assert {i.instance_id for i in only_c1} == {"i1"}


@pytest.mark.asyncio
async def test_remove_instance_orphans_children():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(
            asset_id="parent_def",
            kind=LayerKind.STRUCTURE,
            base_prompt="x",
            sockets=(Socket(name="lap", x=0.5, y=0.5),),
        )
    )
    await store.register_definition(
        AssetDefinition(asset_id="child_def", kind=LayerKind.CHARACTER, base_prompt="y")
    )
    parent = AssetInstance(instance_id="P", canvas_id="c_1", definition="parent_def")
    child = AssetInstance(
        instance_id="C",
        canvas_id="c_1",
        definition="child_def",
        parent_id="P",
        parent_socket="lap",
    )
    await store.upsert_instance(parent)
    await store.upsert_instance(child)

    await store.remove_instance("P")
    out = await store.get_instance("C")
    assert out is not None
    assert out.parent_id is None
    assert out.parent_socket is None


@pytest.mark.asyncio
async def test_instance_round_trip_preserves_all_fields():
    store = InMemoryAssetStore()
    await store.register_definition(
        AssetDefinition(asset_id="a", kind=LayerKind.STRUCTURE, base_prompt="x")
    )
    original = AssetInstance(
        instance_id="i_full",
        canvas_id="c_1",
        definition="a",
        parent_id="P",
        parent_socket="porch",
        transform=Transform(tx=10.0, ty=5.0, sx=1.5, sy=1.5, rotation=15.0),
        anchor=Anchor.GROUND_CONTACT,
        occlusion=OcclusionHint(in_front_of=("X",), behind=("Y",)),
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
        skin_binding={"protagonist": "sarah"},
        prompt_nudge="covered in snow",
        visible=False,
        locked=True,
        history=("/old.png", "/older.png"),
        z_index=42,
    )
    await store.upsert_instance(original)
    out = await store.get_instance("i_full")
    assert out == original


# ─────────────────────────────────────────────────────────────────────
# ChildProfile
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_profile_round_trip():
    store = InMemoryAssetStore()
    profile = ChildProfile(
        profile_id="p_sarah",
        name="Sarah",
        pronouns="she/her",
        likeness_refs=("/photo1.jpg", "/photo2.jpg"),
        accommodations=("headphones", "fidget"),
        age_range="5-7",
        reading_level="early",
    )
    await store.upsert_profile(profile)
    out = await store.get_profile("p_sarah")
    assert out == profile


# ─────────────────────────────────────────────────────────────────────
# Book / WorldStyle / StyleVolume
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_book_persists_world_style_and_volumes():
    store = InMemoryAssetStore()
    base = _world_style()
    sv = StyleVolume(
        page_range=(7, 9),
        partial_world_style=WorldStylePartial(realism="cel"),
    )
    book = await store.create_book(
        book_id="b_1",
        title="Test Book",
        world_style=base,
        style_volumes=(sv,),
    )
    assert book.title == "Test Book"
    out = await store.get_book("b_1")
    assert out is not None
    assert out.world_style == base
    assert out.style_volumes == (sv,)


@pytest.mark.asyncio
async def test_create_book_rejects_inverted_page_range():
    store = InMemoryAssetStore()
    sv = StyleVolume(page_range=(9, 7))  # ADR-039 EC-10
    with pytest.raises(ValueError, match="page_range start > end"):
        await store.create_book(
            book_id="b_1",
            title="Bad",
            world_style=_world_style(),
            style_volumes=(sv,),
        )


@pytest.mark.asyncio
async def test_create_book_rejects_duplicate_id():
    store = InMemoryAssetStore()
    await store.create_book(book_id="b_1", title="A", world_style=_world_style())
    with pytest.raises(ValueError, match="already exists"):
        await store.create_book(book_id="b_1", title="B", world_style=_world_style())


@pytest.mark.asyncio
async def test_update_book_round_trip():
    store = InMemoryAssetStore()
    book = await store.create_book(book_id="b_1", title="A", world_style=_world_style())
    book.title = "A Different Title"
    out = await store.update_book(book)
    assert out.title == "A Different Title"
    fresh = await store.get_book("b_1")
    assert fresh is not None
    assert fresh.title == "A Different Title"


@pytest.mark.asyncio
async def test_pose_geometry_serializes_for_character_pose():
    """ADR-039 §8 — CharacterPose carries named bones."""
    store = InMemoryAssetStore()
    pose = CharacterPose(
        bones={"head": (0.5, 0.2), "hand_l": (0.3, 0.6)},
        facial_keypoints={"left_eye": (0.45, 0.18)},
    )
    defn = AssetDefinition(
        asset_id="char_pose",
        kind=LayerKind.CHARACTER,
        base_prompt="x",
        pose_geometry=pose,
    )
    await store.register_definition(defn)
    out = await store.get_definition("char_pose")
    assert out is not None
    assert out.pose_geometry == pose
