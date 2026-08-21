"""Boundary + behavioural tests for ADR-041 asset compositor."""

from __future__ import annotations

import pytest

from maistro_canvas.canvas.asset_compositor import (
    RenderPlan,
    build_scene_graph,
    compile_personalization,
    compose_prompt,
    plan_render,
    resolve_occlusion_order,
)
from maistro_canvas.layers import (
    Anchor,
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    ChildProfile,
    LayerKind,
    OcclusionHint,
    PersonalizationSlot,
    RenderStyle,
    Socket,
    StyleVolume,
    Transform,
    WorldStyle,
    WorldStylePartial,
)
from maistro_canvas.types import OcclusionCycleError, SkinBindingError


def _ws(**overrides: object) -> WorldStyle:
    base = {
        "era": "modern",
        "realism": "watercolor",
        "architectural_register": "cottage",
        "vehicle_register": "1970s-pickup",
        "palette_anchors": ("sage", "cream"),
        "fauna_realism": "cute",
    }
    base.update(overrides)  # type: ignore[arg-type]
    return WorldStyle(**base)  # type: ignore[arg-type]


def _instance(iid: str, **kwargs: object) -> AssetInstance:
    defaults: dict[str, object] = {
        "instance_id": iid,
        "canvas_id": "c_1",
        "definition": "a",
    }
    defaults.update(kwargs)
    return AssetInstance(**defaults)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────
# Scene graph
# ─────────────────────────────────────────────────────────────────────


def test_build_scene_graph_groups_into_tree():
    roots = build_scene_graph(
        [
            _instance("P", parent_id=None),
            _instance("C1", parent_id="P", parent_socket="lap"),
            _instance("C2", parent_id="P"),
            _instance("R2", parent_id=None),
        ]
    )
    assert {r.instance.instance_id for r in roots} == {"P", "R2"}
    p = next(r for r in roots if r.instance.instance_id == "P")
    assert {c.instance.instance_id for c in p.children} == {"C1", "C2"}


def test_build_scene_graph_rejects_missing_parent():
    with pytest.raises(ValueError, match="missing parent"):
        build_scene_graph([_instance("C", parent_id="ghost")])


def test_build_scene_graph_rejects_duplicate_id():
    with pytest.raises(ValueError, match="Duplicate"):
        build_scene_graph([_instance("X"), _instance("X")])


def test_build_scene_graph_rejects_two_node_cycle():
    # A's parent is B, B's parent is A.
    a = _instance("A", parent_id="B")
    b = _instance("B", parent_id="A")
    with pytest.raises(ValueError, match="Cycle"):
        build_scene_graph([a, b])


# ─────────────────────────────────────────────────────────────────────
# Transform composition
# ─────────────────────────────────────────────────────────────────────


def test_plan_render_composes_transforms_parent_to_child():
    parent = _instance("P", definition="d", transform=Transform(tx=10.0, ty=5.0, sx=2.0, sy=2.0))
    child = _instance(
        "C",
        definition="d",
        parent_id="P",
        transform=Transform(tx=1.0, ty=1.0, sx=0.5, sy=0.5),
    )
    plan = plan_render(canvas_id="c", instances=[parent, child], world_style=_ws())
    by_id = {r.instance_id: r for r in plan.rendered}
    p_t = by_id["P"].resolved_transform
    c_t = by_id["C"].resolved_transform
    # Parent: identity composed with itself, so its transform stays.
    assert p_t.tx == 10.0 and p_t.ty == 5.0 and p_t.sx == 2.0 and p_t.sy == 2.0
    # Child: parent.tx + child.tx * parent.sx = 10 + 1 * 2 = 12.
    # Scale: 2.0 * 0.5 = 1.0.
    assert c_t.tx == 12.0
    assert c_t.ty == 7.0
    assert c_t.sx == 1.0
    assert c_t.sy == 1.0


# ─────────────────────────────────────────────────────────────────────
# Occlusion ordering
# ─────────────────────────────────────────────────────────────────────


def test_resolve_occlusion_orders_in_front_of_after():
    # A in_front_of B → B comes before A.
    a = _instance("A", occlusion=OcclusionHint(in_front_of=("B",)))
    b = _instance("B")
    out = resolve_occlusion_order([a, b])
    assert [i.instance_id for i in out] == ["B", "A"]


def test_resolve_occlusion_orders_behind_before():
    # A behind C → A comes before C.
    a = _instance("A", occlusion=OcclusionHint(behind=("C",)))
    c = _instance("C")
    out = resolve_occlusion_order([a, c])
    assert [i.instance_id for i in out] == ["A", "C"]


def test_resolve_occlusion_breaks_ties_on_z_index():
    a = _instance("A", z_index=10)
    b = _instance("B", z_index=0)
    c = _instance("C", z_index=5)
    out = resolve_occlusion_order([a, b, c])
    assert [i.instance_id for i in out] == ["B", "C", "A"]


def test_resolve_occlusion_self_loop_raises():
    a = _instance("A", occlusion=OcclusionHint(in_front_of=("A",)))
    with pytest.raises(OcclusionCycleError, match="self-loop"):
        resolve_occlusion_order([a])


def test_resolve_occlusion_two_cycle_raises():
    a = _instance("A", occlusion=OcclusionHint(in_front_of=("B",)))
    b = _instance("B", occlusion=OcclusionHint(in_front_of=("A",)))
    with pytest.raises(OcclusionCycleError):
        resolve_occlusion_order([a, b])


def test_resolve_occlusion_unknown_target_raises():
    a = _instance("A", occlusion=OcclusionHint(in_front_of=("ghost",)))
    with pytest.raises(OcclusionCycleError, match="unknown instance"):
        resolve_occlusion_order([a])


def test_resolve_occlusion_three_layer_chain():
    # Character C in_front_of tree T, behind fence F.
    # Expected order: T, C, F.
    c = _instance("C", occlusion=OcclusionHint(in_front_of=("T",), behind=("F",)))
    t = _instance("T")
    f = _instance("F")
    out = resolve_occlusion_order([c, t, f])
    ids = [i.instance_id for i in out]
    assert ids.index("T") < ids.index("C") < ids.index("F")


# ─────────────────────────────────────────────────────────────────────
# Personalisation
# ─────────────────────────────────────────────────────────────────────


def test_compile_personalization_child_likeness_uses_normalised_name():
    profile = ChildProfile(profile_id="p", name="Sarah")
    instance = _instance(
        "I",
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
    )
    [out] = compile_personalization([instance], profile)
    assert out.skin_binding == {"protagonist": "sarah"}


def test_compile_personalization_normalises_punctuation():
    profile = ChildProfile(profile_id="p", name="O'Hara!")
    instance = _instance(
        "I",
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
    )
    [out] = compile_personalization([instance], profile)
    assert out.skin_binding == {"protagonist": "ohara"}


def test_compile_personalization_companion_uses_binding_name():
    instance = _instance(
        "I",
        personalization=PersonalizationSlot(kind="companion", binding="best_friend"),
    )
    [out] = compile_personalization([instance], None)
    assert out.skin_binding == {"best_friend": "best_friend"}


def test_compile_personalization_passthrough_for_no_slot():
    instance = _instance("I")
    [out] = compile_personalization([instance], None)
    assert out is instance  # unchanged when no slot


def test_compile_personalization_raises_when_skin_set_excludes():
    inline = AssetDefinition(
        asset_id="",
        kind=LayerKind.CHARACTER,
        base_prompt="x",
        skin_set={"protagonist": ("tom", "mei")},
    )
    instance = _instance(
        "I",
        definition=inline,
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
    )
    profile = ChildProfile(profile_id="p", name="Sarah")  # not in skin_set
    with pytest.raises(SkinBindingError, match="not in"):
        compile_personalization(
            [instance],
            profile,
            registry=lambda _: None,  # registry not used because definition is inline
        )


def test_compile_personalization_passes_when_skin_in_set():
    inline = AssetDefinition(
        asset_id="",
        kind=LayerKind.CHARACTER,
        base_prompt="x",
        skin_set={"protagonist": ("tom", "sarah", "mei")},
    )
    instance = _instance(
        "I",
        definition=inline,
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
    )
    profile = ChildProfile(profile_id="p", name="Sarah")
    [out] = compile_personalization([instance], profile, registry=lambda _: None)
    assert out.skin_binding == {"protagonist": "sarah"}


def test_compile_personalization_raises_without_profile_for_likeness():
    instance = _instance(
        "I",
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
    )
    with pytest.raises(SkinBindingError, match="requires a ChildProfile"):
        compile_personalization([instance], None)


# ─────────────────────────────────────────────────────────────────────
# Prompt composition
# ─────────────────────────────────────────────────────────────────────


def test_compose_prompt_basic():
    s = compose_prompt(world_style=_ws(), base_prompt="a small farmhouse")
    assert "era: modern" in s
    assert "realism: watercolor" in s
    assert "a small farmhouse" in s


def test_compose_prompt_volume_overrides_realism_for_in_range_page():
    sv = StyleVolume(
        page_range=(7, 9),
        partial_world_style=WorldStylePartial(realism="cel"),
    )
    s_in_range = compose_prompt(
        world_style=_ws(), style_volumes=[sv], page_index=8, base_prompt="x"
    )
    s_out = compose_prompt(world_style=_ws(), style_volumes=[sv], page_index=3, base_prompt="x")
    assert "realism: cel" in s_in_range
    assert "realism: watercolor" in s_in_range or "realism: watercolor" not in s_in_range
    assert "realism: cel" not in s_out
    assert "realism: watercolor" in s_out


def test_compose_prompt_later_volume_wins():
    sv1 = StyleVolume(
        page_range=(1, 100),
        partial_world_style=WorldStylePartial(realism="cel"),
    )
    sv2 = StyleVolume(
        page_range=(1, 100),
        partial_world_style=WorldStylePartial(realism="line"),
    )
    s = compose_prompt(
        world_style=_ws(),
        style_volumes=[sv1, sv2],
        page_index=10,
        base_prompt="x",
    )
    assert "realism: line" in s
    assert "realism: cel" not in s


def test_compose_prompt_includes_render_style_token():
    s = compose_prompt(
        world_style=_ws(),
        render_style=RenderStyle(style_token="dreamy"),
        base_prompt="x",
    )
    assert "style: dreamy" in s


def test_compose_prompt_skips_empty_fields():
    s = compose_prompt(world_style=_ws(), base_prompt="x")
    # No double semicolons.
    assert ";;" not in s


def test_compose_prompt_skin_binding_appended_when_present():
    s = compose_prompt(
        world_style=_ws(),
        base_prompt="hero",
        skin_binding={"protagonist": "sarah"},
    )
    assert "as sarah" in s


def test_compose_prompt_deterministic():
    a = compose_prompt(world_style=_ws(), base_prompt="x", prompt_nudge="under snow")
    b = compose_prompt(world_style=_ws(), base_prompt="x", prompt_nudge="under snow")
    assert a == b


# ─────────────────────────────────────────────────────────────────────
# plan_render
# ─────────────────────────────────────────────────────────────────────


def test_plan_render_round_trip_basic():
    farm_def = AssetDefinition(
        asset_id="farmhouse",
        kind=LayerKind.STRUCTURE,
        base_prompt="a small red farmhouse",
        sockets=(Socket(name="porch", x=0.5, y=0.6),),
    )
    char_def = AssetDefinition(
        asset_id="protag",
        kind=LayerKind.CHARACTER,
        base_prompt="a young child",
        skin_set={"protagonist": ("sarah",)},
    )
    farm = _instance("FH", definition="farmhouse")
    sarah = _instance(
        "SARAH",
        definition="protag",
        parent_id="FH",
        parent_socket="porch",
        personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist"),
        z_index=1,
    )
    profile = ChildProfile(profile_id="p", name="Sarah")
    registry = {
        "farmhouse": farm_def,
        "protag": char_def,
    }
    plan = plan_render(
        canvas_id="c_1",
        instances=[farm, sarah],
        world_style=_ws(),
        profile=profile,
        registry_lookup=registry.get,
    )
    assert isinstance(plan, RenderPlan)
    by_id = {r.instance_id: r for r in plan.rendered}
    # Both instances are in the plan.
    assert set(by_id.keys()) == {"FH", "SARAH"}
    # Skin bound from the profile.
    assert by_id["SARAH"].skin_binding == {"protagonist": "sarah"}
    # Sarah's parent_chain has the farmhouse.
    assert by_id["SARAH"].parent_chain == ("FH", "SARAH")
    assert by_id["FH"].parent_chain == ("FH",)
    # Sarah's prompt mentions the skin binding.
    assert "as sarah" in by_id["SARAH"].prompt


def test_plan_render_includes_asset_sheet_ref_when_definition_has_sheet():
    sheet = AssetSheet(
        asset_id="farmhouse",
        refs=("/r1.png", "/r2.png", "/r3.png"),
        sheet_image="/sheet.png",
    )
    farm_def = AssetDefinition(
        asset_id="farmhouse",
        kind=LayerKind.STRUCTURE,
        base_prompt="x",
        asset_sheet=sheet,
    )
    farm = _instance("FH", definition="farmhouse")
    plan = plan_render(
        canvas_id="c",
        instances=[farm],
        world_style=_ws(),
        registry_lookup={"farmhouse": farm_def}.get,
    )
    [r] = plan.rendered
    assert r.asset_sheet_ref == "/sheet.png"


def test_plan_render_pure_function_same_inputs_same_outputs():
    farm = _instance("FH")
    a = plan_render(canvas_id="c", instances=[farm], world_style=_ws())
    b = plan_render(canvas_id="c", instances=[farm], world_style=_ws())
    assert a == b


def test_plan_render_orders_by_occlusion_then_z_index():
    # Three layers: tree (z=2), character (z=5, behind nothing),
    # fence (z=0). Character in_front_of tree.
    tree = _instance("T", z_index=2)
    fence = _instance("F", z_index=0)
    char = _instance(
        "C",
        z_index=5,
        occlusion=OcclusionHint(in_front_of=("T",)),
    )
    plan = plan_render(
        canvas_id="c",
        instances=[tree, fence, char],
        world_style=_ws(),
    )
    ids = [r.instance_id for r in plan.rendered]
    # Fence has lowest z and no constraints — first.
    assert ids[0] == "F"
    # Character must come after tree.
    assert ids.index("C") > ids.index("T")


def test_plan_render_propagates_occlusion_cycle_error():
    a = _instance("A", occlusion=OcclusionHint(in_front_of=("B",)))
    b = _instance("B", occlusion=OcclusionHint(in_front_of=("A",)))
    with pytest.raises(OcclusionCycleError):
        plan_render(canvas_id="c", instances=[a, b], world_style=_ws())


def test_planned_render_carries_z_index():
    a = _instance("A", z_index=42)
    plan = plan_render(canvas_id="c", instances=[a], world_style=_ws())
    [r] = plan.rendered
    assert r.z_index == 42


def test_plan_render_inline_definition_resolves_base_prompt():
    inline = AssetDefinition(
        asset_id="",
        kind=LayerKind.FX,
        base_prompt="a wispy cloud",
    )
    cloud = _instance("CLD", definition=inline, anchor=Anchor.FLOATING)
    plan = plan_render(canvas_id="c", instances=[cloud], world_style=_ws())
    [r] = plan.rendered
    assert "a wispy cloud" in r.prompt
