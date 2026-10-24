---
id: SPEC-229
title: "Canvas asset compositor: scene graph, occlusion, prompt composition (pure logic)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-067
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-canvas/tests/test_asset_compositor.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-229: Canvas asset compositor

## Context

ADR-067 specified a pure-logic scene-graph compositor for the canvas ability,
separate from pixel compositing (owned by the legacy PIL `compositor.py`). It builds
a scene tree, resolves occlusion order, compiles personalization bindings, composes
per-instance prompts, and produces an ordered `RenderPlan`. This is implemented and
tested; this SPEC documents the shipped module.

## Goals

- Document the actual module surface in `asset_compositor.py` and confirm it has zero
  PIL dependency.
- Map ADR-067's boundary/behavioral contracts to the real test suite.

## Non-goals

- Pixel rendering/blending (owned by `compositor.py` and the image-generation backend).
- Layer image caching/invalidation policy.
- Server-side PDF rasterization.
- Migrating `LayerRecord` flat rows to `AssetInstance`.

## Decision

`packages/maistro-canvas/src/maistro_canvas/canvas/asset_compositor.py` (577 lines),
imports only `re`, `collections.abc`, `dataclasses`, `maistro_canvas.layers`,
`maistro_canvas.types` — no PIL/Pillow import.

Public surface (matches the ADR closely; two minor signature differences noted):

```python
class SceneNode: ...                     # tree node wrapping AssetInstance + children

@dataclass(frozen=True)
class PlannedRender:
    instance_id: str
    parent_chain: tuple[str, ...]
    resolved_transform: Transform
    prompt: str
    asset_sheet_ref: str | None
    skin_binding: dict[str, str] | None
    z_index: int

@dataclass(frozen=True)
class RenderPlan:
    canvas_id: str
    page_index: int | None
    world_style: WorldStyle
    rendered: tuple[PlannedRender, ...]

def build_scene_graph(instances: Iterable[AssetInstance]) -> list[SceneNode]: ...
def resolve_occlusion_order(instances: Sequence[AssetInstance]) -> list[AssetInstance]: ...
def compile_personalization(
    instances: Sequence[AssetInstance],
    profile: ChildProfile | None,
    *,
    registry: Callable[[str], AssetDefinition | None] | None = None,  # ADR text says AssetRegistry | None
) -> list[AssetInstance]: ...
def compose_prompt(
    *, world_style, style_volumes: Sequence[StyleVolume] = (),  # ADR text has no default
    page_index, render_style, base_prompt, prompt_nudge, skin_binding=None,
) -> str: ...
def plan_render(*, canvas_id, instances, world_style, style_volumes=(), page_index=None,
                 render_style=None, profile=None, registry_lookup=None) -> RenderPlan: ...
```

Boundary contracts (all enforced and tested): `build_scene_graph` raises `ValueError`
on a missing-parent reference or a parent-chain cycle; `resolve_occlusion_order` raises
`OcclusionCycleError` on cycles (including self-loops and unknown targets);
`compile_personalization` raises `SkinBindingError` when a `PersonalizationSlot`
binding is absent from the parent definition's `skin_set`.

Behavioral contracts (all enforced and tested): transform composition is associative
(parent ∘ child, depth-first from roots); occlusion order is topological
(`in_front_of`/`behind` respected, ties broken by `z_index` then insertion order);
`compose_prompt` is deterministic with fixed composition order
(`world_style → matching style_volume → render_style → base_prompt → prompt_nudge →
skin_binding`) and page-range-scoped style-volume overrides (later wins);
personalization is total after `compile_personalization` (every slotted instance gets
a non-None `skin_binding` or the call raises); `plan_render` is a pure function of its
inputs.

Related files confirmed present: `packages/maistro-canvas/src/maistro_canvas/layers.py`
(types), `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`
(ADR-040 persistence), `packages/maistro-canvas/src/maistro_canvas/canvas/compositor.py`
(legacy PIL compositor, unchanged).

## Acceptance criteria

- [x] `build_scene_graph` raises `ValueError` on missing parent reference
- [x] `build_scene_graph` raises `ValueError` on parent-chain cycle
- [x] `resolve_occlusion_order` raises `OcclusionCycleError` on cycles (incl. self-loops, unknown targets)
- [x] `compile_personalization` raises `SkinBindingError` on unbound skin slot
- [x] `plan_render` orders by occlusion, then `z_index` ascending, then insertion order (stable)
- [x] `compose_prompt` is total (missing fields fall back to base + nudge)
- [x] Transform composition is associative (parent ∘ child, depth-first)
- [x] Occlusion order is topological, respecting `in_front_of`/`behind` pairs
- [x] `compose_prompt` is deterministic with fixed field order and page-range-scoped, later-wins style volumes
- [x] Personalization is total after compile (every slotted instance has `skin_binding` or call raised)
- [x] `plan_render` is a pure function of its inputs
- [x] Module has zero PIL dependency

## Testing

`packages/maistro-canvas/tests/test_asset_compositor.py` (33 tests), including:
`test_build_scene_graph_groups_into_tree`, `test_build_scene_graph_rejects_missing_parent`,
`test_build_scene_graph_rejects_duplicate_id`, `test_build_scene_graph_rejects_two_node_cycle`,
`test_plan_render_composes_transforms_parent_to_child`,
`test_resolve_occlusion_orders_in_front_of_after`, `test_resolve_occlusion_orders_behind_before`,
`test_resolve_occlusion_breaks_ties_on_z_index`, `test_resolve_occlusion_self_loop_raises`,
`test_resolve_occlusion_two_cycle_raises`, `test_resolve_occlusion_unknown_target_raises`,
`test_resolve_occlusion_three_layer_chain`,
`test_compile_personalization_child_likeness_uses_normalised_name`,
`test_compile_personalization_normalises_punctuation`,
`test_compile_personalization_companion_uses_binding_name`,
`test_compile_personalization_passthrough_for_no_slot`,
`test_compile_personalization_raises_when_skin_set_excludes`,
`test_compile_personalization_passes_when_skin_in_set`,
`test_compile_personalization_raises_without_profile_for_likeness`,
`test_compose_prompt_basic`, `test_compose_prompt_volume_overrides_realism_for_in_range_page`,
`test_compose_prompt_later_volume_wins`, `test_compose_prompt_includes_render_style_token`,
`test_compose_prompt_skips_empty_fields`, `test_compose_prompt_skin_binding_appended_when_present`,
`test_compose_prompt_deterministic`, `test_plan_render_round_trip_basic`,
`test_plan_render_includes_asset_sheet_ref`, `test_plan_render_pure_function_same_inputs_same_outputs`,
`test_plan_render_orders_by_occlusion_then_z_index`,
`test_plan_render_propagates_occlusion_cycle_error`, `test_planned_render_carries_z_index`,
`test_plan_render_inline_definition_resolves_base_prompt`.

## Open questions

- ADR-042 (routes) and ADR-043 (executor + tool) are the planned consumers of
  `plan_render` — confirm whether those ADRs have their own SPECs covering the wiring.
- The legacy PIL `compositor.py` consuming `RenderPlan` directly is explicitly future
  work (ADR-067 "Out of scope") — no SPEC needed until that lands.

## References

- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_compositor.py`
- `packages/maistro-canvas/src/maistro_canvas/layers.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/compositor.py`
- `packages/maistro-canvas/tests/test_asset_compositor.py`
