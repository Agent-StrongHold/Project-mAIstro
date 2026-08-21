---
id: SPEC-219
title: "Canvas layer taxonomy, scene graph, asset model, and world style (types)"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate:
  - maistro-engine#ADR-005
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-036
  - maistro-engine#ADR-041
implements:
  - maistro-engine#ADR-041
related:
  - maistro-engine#SPEC-220
  - maistro-engine#SPEC-221
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-219: Canvas layer taxonomy, scene graph, asset model, and world style (types)

## Context

The original canvas layer model had only four `LayerType`s
(`background | character | object | text`), with no scene graph, no
asset-definition/instance split, and no first-class personalisation or
world-style model — making the personalised illustrated-book product
unbuildable: backgrounds, structures, vehicles, and props all collapsed
into one catch-all `OBJECT` type with no typed attachment points or
cross-page consistency. ADR-041 decided to ship a 7-kind layer taxonomy,
a scene graph with named sockets, an asset-definition/instance split with
inline support, and a world-style/render-style model with page-range
overrides — as **types and contracts only**; implementation (compositor,
executor, routes, store) landed in follow-up ADRs/specs.

## Goals

- Replace the 4-value `LayerType` with a 7-value `LayerKind`
  (`BACKGROUND, STRUCTURE, VEHICLE, PROP, CHARACTER, FX, TEXT`), keeping
  `LayerType` as a deprecated alias so existing `LayerRecord` rows still
  validate.
- A scene graph via `parent_id` + `parent_socket` on `AssetInstance`,
  replacing most of the old flat `Anchor` enum with transform
  inheritance.
- An `AssetDefinition`/`AssetInstance` split supporting both named
  (registry) and inline (anonymous, one-off) definitions.
- A generalized `AssetSheet` (reference sheet) for any named asset, not
  just characters.
- `PersonalizationSlot` + skin-binding for declarative personalisation
  (child name/likeness/companion/etc.).
- `WorldStyle` / `WorldStylePartial` / `RenderStyle` / `StyleVolume` for
  page-range style overrides (dream sequences, flashbacks) without
  polluting the canonical book style.
- `BackgroundComposition` with a typed `GroundPlane` other layers anchor
  against, plus kind-discriminated `PoseGeometry`
  (`FoundationFootprint | WheelAnchors | CharacterPose`).

## Non-goals

- Implementation in `compositor.py`/`executor.py`/`routes.py`/`store.py`/
  `tool.py` — covered by SPEC-220 (store) and SPEC-221 (executor + tool);
  compositor/routes are out of scope for this spec cluster.
- USD export, per-tenant world-style overrides, skin-set validation
  lints, LoRA fine-tune graduation policy — all explicitly v2.0/out of
  scope per ADR-041.
- Database migration of existing `LayerType.OBJECT` rows to the new
  taxonomy — deferred, human-reviewed, not automatic.

## Decision

All types live in `packages/maistro-canvas/src/maistro_canvas/layers.py`:

```python
class LayerKind(StrEnum):
    BACKGROUND, STRUCTURE, VEHICLE, PROP, CHARACTER, FX, TEXT

class Anchor(StrEnum):
    GROUND_CONTACT, HORIZON, FLOATING

@dataclass(frozen=True) class Slot: x, y, w, h
@dataclass(frozen=True) class Socket: name, x, y, role
@dataclass(frozen=True) class OcclusionHint: in_front_of, behind
@dataclass(frozen=True) class Transform: ...
@dataclass(frozen=True) class GroundPlane: horizon_y, vanishing_x, perspective
@dataclass(frozen=True) class BackgroundComposition: sky, mid, foreground, ground_plane
@dataclass(frozen=True) class FoundationFootprint: polygon
@dataclass(frozen=True) class WheelAnchors: points
@dataclass(frozen=True) class CharacterPose: bones, facial_keypoints
@dataclass(frozen=True) class PersonalizationSlot: kind, binding
@dataclass(frozen=True) class ChildProfile: profile_id, name, pronouns, likeness_refs, accommodations, age_range, reading_level
@dataclass(frozen=True) class AssetSheet: asset_id, refs, sheet_image, revision, generation_params
@dataclass(frozen=True) class WorldStylePartial: era, realism, architectural_register, vehicle_register, palette_anchors, fauna_realism
@dataclass(frozen=True) class AssetDefinition: asset_id, kind, base_prompt, asset_sheet, sockets, skin_set, default_world_style
@dataclass class AssetInstance: instance_id, canvas_id, definition, parent_id, parent_socket, transform, slot, anchor, occlusion, personalization, skin_binding, prompt_nudge, visible, locked, history, z_index
@dataclass(frozen=True) class WorldStyle: era, realism, architectural_register, vehicle_register, palette_anchors, fauna_realism
@dataclass(frozen=True) class RenderStyle: style_token, palette_override, line_weight
@dataclass(frozen=True) class StyleVolume: page_range, partial_world_style, partial_render_style
```

New domain errors in `types.py`: `UnknownLayerKindError`,
`MissingAnchorError`, `OcclusionCycleError`, `AssetSheetNotFoundError`,
`AssetDefinitionNotFoundError`, `WorldStyleConflictError`,
`MissingSocketError`, `SkinBindingError`, `PoseGeometryMismatchError`.

`AssetSheetService` and `AssetRegistry` Protocols are added to
`protocols.py`.

## Acceptance criteria

- [x] `LayerKind` has 7 values; `LayerType` remains as a usable
      deprecated alias
- [x] `AssetInstance.definition` accepts either a registry id (`str`) or
      an inline `AssetDefinition`
- [x] `AssetSheet` is generalized (not character-only) — any `asset_id`
      can have a sheet
- [x] `PersonalizationSlot` + `skin_binding` types exist for declarative
      personalisation
- [x] `WorldStyle`/`WorldStylePartial`/`RenderStyle`/`StyleVolume` types
      exist for page-range style overrides
- [x] `BackgroundComposition` carries a typed `GroundPlane`
- [x] `PoseGeometry` is a discriminated union of `FoundationFootprint |
      WheelAnchors | CharacterPose`
- [x] All new domain errors (`UnknownLayerKindError`,
      `MissingSocketError`, `OcclusionCycleError`, etc.) are defined
- [ ] `OcclusionHint` references form a DAG (no cycles) — enforced at
      validation time (not independently re-verified against a test in
      this pass; recommend confirming `OcclusionCycleError` is actually
      raised somewhere before relying on it)

## Testing

No dedicated `tests/test_layers.py` was located; type-level behaviour is
exercised indirectly through `test_asset_store.py`,
`test_asset_compositor.py`, and `test_asset_executor_and_tool.py`, which
construct and pass these types through the store/compositor/executor.

## Open questions

- Whether `OcclusionHint` cycle detection is actually wired up anywhere,
  or only declared as a contract in ADR-041 — needs verification before
  the corresponding acceptance criterion can be checked off.
- Database migration ADR for existing `LayerType.OBJECT` rows is still
  TBD per ADR-041.

## References

- [ADR-005: Pydantic schemas + SCHEMA_REGISTRY](../adr/ADR-005-schemas.md)
- [ADR-031: Front matter and registry](../adr/ADR-031-front-matter-and-registry.md)
- [ADR-036: Ontology / Semantic Object Layer](../adr/ADR-036-ontology-semantic-object-layer.md)
- [ADR-041: Canvas Layer Taxonomy, Scene Graph, and World Style](../adr/ADR-041-canvas-layer-taxonomy-and-world-style.md)
- `packages/maistro-canvas/src/maistro_canvas/layers.py`
- `packages/maistro-canvas/src/maistro_canvas/protocols.py`
