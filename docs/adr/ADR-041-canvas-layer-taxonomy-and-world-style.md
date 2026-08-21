---
id: ADR-041
title: Canvas Layer Taxonomy, Scene Graph, and World Style
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-08
substrate:
  - maistro-engine#ADR-005
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-036
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-030
  - maistro-engine#ADR-040
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
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-08
---

# ADR-041: Canvas Layer Taxonomy, Scene Graph, and World Style

> **Renumbering note (2026-05-09):** Originally filed as ADR-039 in PR #12.
> Renumbered to ADR-041 to resolve a numbering collision with
> `ADR-039-external-library-adoption-policy.md`. ADR-040 is
> `canvas-asset-store`. The follow-up ADRs referenced at the bottom of
> this document are renumbered accordingly.

## Context

`maistro-canvas` ships a layer-based book-builder that today distinguishes
only four `LayerType`s: `background | character | object | text`. The POC
frontend (`packages/maistro-canvas/frontend/SPEC.md`) goes further with
informal concepts that are not encoded in `types.py`:

- A "slot" string (`"full_page"`) used to position layers.
- Two pose anchors (`ground_contact`, `seat_contact`) on character layers.
- Per-page version arrays for style, character, and storyboard.
- Reference photos and a generated character sheet, character-only.

Three gaps make the current model unable to support the personalised
illustrated children's-book product the POC was built for:

1. **`OBJECT` is a catch-all.** Buildings, vehicles, hand-held props, FX,
   and large static props all collapse into one type. Decomposition rules
   in the davinci agent ("decompose scenes into separate layers before
   generating") have nothing typed to decompose into. Architectural props
   need foundation anchors and occlusion in front of characters; vehicles
   need wheel/keel anchors; hand-held props need to attach to a character
   bone. None of that is expressible.
2. **Cross-page consistency is character-only.** The same farmhouse on
   pages 2, 5, 9 has no `AssetSheet` to condition on. The POC keeps only a
   character sheet; the architecture and props re-roll every page.
3. **Personalisation is implicit.** The POC product is a book template
   with swappable parts (child name, child likeness, optional companion).
   Today there is no first-class slot type that says "this layer is the
   protagonist; bind it to the parent's child profile at render time."

Game-engine, 2D-animation, and USD scene-description practice all converge
on the same shapes for these problems: a scene graph with named
attachment sockets, an asset-definition / asset-instance split, a "skin"
or "variant set" for swap-by-name, and a material/style layer that's
decoupled from geometry with optional volume overrides. Adopting these
shapes lets us delete bespoke vocabulary in exchange for one with a
30-year track record.

## Decision

Engine ships ADR-041 as the canvas's typed layer model, scene graph,
asset model, personalisation model, and world-style model, in
`packages/maistro-canvas/src/maistro_canvas/types.py` and
`packages/maistro-canvas/src/maistro_canvas/protocols.py`. The POC's
frontend `SPEC.md` adds a sibling `SPEC-layers.md` covering the
behavioural acceptance scenarios that test these contracts.

This ADR is **types and contracts only**. Implementation in
`compositor.py`, `executor.py`, `routes.py`, `store.py`, and `tool.py`
lands in a follow-up ADR/PR after the contracts are reviewed.

### 1. Layer taxonomy — pragmatic 7-kind split

Replace `LayerType` (4 values) with `LayerKind` (7 values). Keep
`LayerType` as a deprecated alias mapping the four old values onto the
new seven so existing `LayerRecord` rows still validate.

```python
class LayerKind(StrEnum):
    BACKGROUND   # layered (sky / mid / foreground) with a ground plane
    STRUCTURE    # buildings, walls, bridges, large static props (trees, rocks)
    VEHICLE      # cars, trains, boats, planes; wheel/keel-anchored
    PROP         # hand-held / movable items, attached to a parent socket
    CHARACTER    # pose-anchored, asset-sheet-conditioned
    FX           # weather, sparkles, motion lines; composited last
    TEXT         # canvas-rendered, never baked into images
```

`STRUCTURE` covers what game engines call "props" that don't move
(buildings, fences, trees, rocks). `PROP` is reserved for items that move
or are held. The split is the smallest taxonomy that distinguishes
foundation-anchored static scenery from socket-attached movable objects.

Migration: existing `LayerType.OBJECT` rows map by default to
`LayerKind.PROP`; a `metadata.role: "structure"` flag promotes to
`STRUCTURE`. Migration is human-reviewed, not automatic.

### 2. Scene graph with sockets

Replace the flat z-ordered layer list with a per-layer optional
`parent_id` plus an optional `parent_socket` name on the parent. Sockets
are declared on the `AssetDefinition` (see §3); a `LayerInstance` says
"my parent is layer X, attached at socket `door` (or `lap`, or
`hand_l`)." z-order remains for sibling sorting.

This collapses most of the old `Anchor` enum:

```python
class Anchor(StrEnum):
    GROUND_CONTACT   # standing on the BackgroundComposition.ground_plane
    HORIZON          # placed at horizon line
    FLOATING         # explicit no-anchor (FX, atmospheric)
    # All other "anchors" are now parent_id + parent_socket combinations
```

A character holding a teddy bear is `parent_id=character_42,
parent_socket="hand_l"`. A child sitting on a porch is
`parent_id=farmhouse_7, parent_socket="porch"`. Move the parent and the
child moves with it; this is standard transform inheritance.

### 3. Asset model — definition / instance split with inline support

Every layer is an `AssetInstance`. Every instance has a `definition`
that is **either** a registry id (named, reusable asset) **or** an
inline anonymous `AssetDefinition` object (one-off use).

```python
@dataclass(frozen=True)
class Socket:
    name: str                # "door", "porch", "hand_l", "driver_seat"
    x: float; y: float       # normalized 0..1 within the asset's image
    role: str | None = None  # optional semantic hint

@dataclass(frozen=True)
class AssetDefinition:
    asset_id: str            # "farmhouse_red_v1" — empty for inline
    kind: LayerKind
    base_prompt: str         # canonical prompt that produced the sheet
    asset_sheet: AssetSheet | None
    sockets: tuple[Socket, ...] = ()
    skin_set: dict[str, tuple[str, ...]] | None = None
    default_world_style: WorldStylePartial | None = None

@dataclass
class AssetInstance:
    instance_id: str
    canvas_id: str
    definition: AssetDefinition | str   # str = registry id, object = inline
    parent_id: str | None = None
    parent_socket: str | None = None
    transform: Transform = Transform()
    slot: Slot | None = None
    anchor: Anchor | None = None
    occlusion: OcclusionHint = OcclusionHint()
    personalization: PersonalizationSlot | None = None
    skin_binding: dict[str, str] | None = None
    prompt_nudge: str | None = None
    visible: bool = True
    locked: bool = False
    history: tuple[str, ...] = ()
    z_index: int = 0
```

A registered farmhouse used on three pages is one `AssetDefinition` with
three `AssetInstance`s pointing at it. Editing the definition's
`base_prompt` updates all three pages atomically. A one-off decorative
cloud uses `definition=<inline AssetDefinition>` with no registry entry.
The agent (davinci) may promote inline → registered automatically when
it detects reuse.

### 4. Reference sheet — generalised to all named assets

```python
@dataclass(frozen=True)
class AssetSheet:
    asset_id: str            # matches the AssetDefinition
    refs: tuple[str, ...]    # 3-5 source images (paths or urls)
    sheet_image: str         # the generated multi-angle/state composite
    revision: int            # bumps when refs or generation regenerates
    generation_params: dict[str, Any] = field(default_factory=dict)
```

Same shape that today serves only characters, generalised to
`STRUCTURE`, `VEHICLE`, `PROP`. v1 retains the existing character-sheet
workflow (3-5 refs → IP-Adapter / FaceID conditioning → 12-pose sheet)
and extends it to any asset with a stable `asset_id`. A per-asset LoRA
fine-tune is an opt-in `revision` graduation when sample count permits.

### 5. Personalisation — `Skin` is the mechanism, `PersonalizationSlot` is sugar

```python
@dataclass(frozen=True)
class PersonalizationSlot:
    kind: Literal[
        "child_name", "child_likeness", "companion", "pet",
        "gift", "place_name", "pronouns",
    ]
    binding: str             # key into ChildProfile / BookVariables

@dataclass(frozen=True)
class ChildProfile:
    profile_id: str
    name: str
    pronouns: str | None = None
    likeness_refs: tuple[str, ...] = ()    # photos
    accommodations: tuple[str, ...] = ()   # "headphones", "AAC", "fidget", "comfort_object"
    age_range: str | None = None
    reading_level: str | None = None
```

`PersonalizationSlot` declares intent. At render time the engine
compiles it into a `skin_binding` on the parent `AssetDefinition`'s
`skin_set`, mirroring Spine "skins" and USD `variantSet`. A book template
declares `skin_set={"protagonist": ("tom", "sarah", "mei")}`; a render
binds `skin_binding={"protagonist": "sarah"}`. The
`PersonalizationSlot` carries the *why* (this slot is the protagonist),
the skin carries the *how* (which variant to render).

### 6. World style + render style with volume overrides

```python
@dataclass(frozen=True)
class WorldStyle:
    era: str                 # "modern", "victorian", "fantasy-medieval", ...
    realism: Literal["cel", "painterly", "watercolor", "photoreal", "line"]
    architectural_register: str    # "cottage", "brownstone", "castle", ...
    vehicle_register: str          # "1970s-pickup", "sailboat", "spaceship", ...
    palette_anchors: tuple[str, ...]
    fauna_realism: Literal["cute", "realistic"]

@dataclass(frozen=True)
class WorldStylePartial:
    """Sparse overrides; any field None inherits from the parent."""
    era: str | None = None
    realism: Literal["cel", "painterly", "watercolor", "photoreal", "line"] | None = None
    architectural_register: str | None = None
    vehicle_register: str | None = None
    palette_anchors: tuple[str, ...] | None = None
    fauna_realism: Literal["cute", "realistic"] | None = None

@dataclass(frozen=True)
class RenderStyle:
    """Per-image overrides applied above WorldStyle."""
    style_token: str | None = None
    palette_override: tuple[str, ...] | None = None
    line_weight: float | None = None

@dataclass(frozen=True)
class StyleVolume:
    """Page-range world-style override. Models dream sequences, flashbacks."""
    page_range: tuple[int, int]    # inclusive
    partial_world_style: WorldStylePartial | None = None
    partial_render_style: RenderStyle | None = None
```

A `Book` carries one `WorldStyle` plus zero or more `StyleVolume`s. A
generation prompt is `WorldStyle ⊕ matching StyleVolume.partial ⊕
RenderStyle ⊕ layer prompt`, composed left-to-right with later wins.
This gives us the dream-sequence shape for free without polluting the
canonical world style.

### 7. BackgroundComposition with ground plane

`BACKGROUND` layers carry a sub-image triplet plus a typed ground plane
that other layers can anchor against:

```python
@dataclass(frozen=True)
class GroundPlane:
    horizon_y: float                          # 0..1 normalised
    vanishing_x: float | None = None
    perspective: Literal["flat", "one_point", "two_point", "isometric"] = "flat"

@dataclass(frozen=True)
class BackgroundComposition:
    sky: str | None = None         # image path or generation prompt fragment
    mid: str | None = None
    foreground: str | None = None
    ground_plane: GroundPlane

@dataclass(frozen=True)
class Slot:
    """Rectangular bounding hint, normalised 0..1."""
    x: float; y: float; w: float; h: float

@dataclass(frozen=True)
class OcclusionHint:
    in_front_of: tuple[str, ...] = ()     # other instance_ids
    behind: tuple[str, ...] = ()          # other instance_ids
```

A character standing in front of a tree but behind a fence:
`occlusion=OcclusionHint(in_front_of=("tree_3",), behind=("fence_2",))`.
The compositor resolves these to a topological z-order at render time.

### 8. Pose geometry, discriminated by kind

```python
@dataclass(frozen=True)
class FoundationFootprint:
    polygon: tuple[tuple[float, float], ...]   # normalised, where the asset meets the ground

@dataclass(frozen=True)
class WheelAnchors:
    points: tuple[tuple[float, float], ...]    # normalised wheel/keel contact points

@dataclass(frozen=True)
class CharacterPose:
    bones: dict[str, tuple[float, float]]      # named bone positions
    facial_keypoints: dict[str, tuple[float, float]] | None = None

PoseGeometry = FoundationFootprint | WheelAnchors | CharacterPose
```

`STRUCTURE` carries a `FoundationFootprint`, `VEHICLE` carries
`WheelAnchors`, `CharacterPose` is for `CHARACTER`. `PROP` and `FX` use
their parent's transform and don't define their own pose.

### 9. v1.0 vs v2.0

**v1.0 ships:**

- `LayerKind`, `Anchor`, `Slot`, `Socket`, `OcclusionHint`,
  `PersonalizationSlot`, `ChildProfile`, `AssetSheet`, `AssetDefinition`,
  `AssetInstance`, `WorldStyle`, `WorldStylePartial`, `RenderStyle`,
  `StyleVolume`, `BackgroundComposition`, `GroundPlane`, pose-geometry
  union.
- Pydantic boundary validation on every type.
- `LayerType` deprecated alias.
- New domain errors: `UnknownLayerKindError`, `MissingAnchorError`,
  `OcclusionCycleError`, `AssetSheetNotFoundError`,
  `WorldStyleConflictError`, `MissingSocketError`, `SkinBindingError`.
- `AssetSheetService` protocol added to `protocols.py`.
- `ImageGenClient.generate` widens to accept `world_style`, `render_style`,
  and `asset_sheet_ref` conditioning.

**v2.0 (out of scope):**

- Implementations in `compositor.py`, `executor.py`, `routes.py`,
  `store.py`, `tool.py`. Separate ADR per file.
- USD export of the layer model.
- Per-tenant world-style overrides for `stronghold`.
- Skin-set validation (multi-skin diff lint, unbound-slot lint).
- LoRA fine-tune graduation policy from `AssetSheet.revision` history.

### 10. Boundary contracts

- Every type above has a Pydantic model. `validate(...)` runs on
  every `AssetInstance` upsert.
- `AssetInstance.definition: AssetDefinition | str` — string form must
  resolve in the registry; object form must validate as a complete
  `AssetDefinition` minus `asset_id` (which may be empty for inline).
- `parent_id` if set must reference a layer on the same canvas.
- `parent_socket` if set must name a socket on the parent's
  `AssetDefinition`.
- `OcclusionHint` references must form a DAG (no cycles, no self-loops).
- `PoseGeometry` must match the `LayerKind`: `STRUCTURE → FoundationFootprint`,
  `VEHICLE → WheelAnchors`, `CHARACTER → CharacterPose`. `PROP`, `FX`,
  `BACKGROUND`, `TEXT` reject pose geometry.
- `WorldStylePartial` fields are mutually independent; setting
  `era="dream"` does not imply `realism="watercolor"`.

### 11. Behavioral contracts

- Editing an `AssetDefinition.base_prompt` invalidates downstream
  generation caches for every instance referencing that definition.
- `WorldStyle ⊕ StyleVolume.partial ⊕ RenderStyle` composition is
  associative within a page's render: order is fixed, result is
  deterministic given identical inputs.
- A page render is a pure function of `(template, child_profile,
  page_index, world_style, style_volumes, layer_seeds)`. Same inputs →
  same outputs. Generation seed is part of the inputs.
- Skin binding is total: every `PersonalizationSlot` on the rendered
  template must resolve to a skin in the parent definition's
  `skin_set`, or rendering raises `SkinBindingError`.
- Inline `AssetDefinition`s never persist beyond the page they are used
  on (they live inside the `AssetInstance`'s row).
- Promoting an inline `AssetDefinition` to a registered one is
  idempotent: the agent runs it on every save; if the asset already
  exists in the registry, the promotion is a no-op.

## Consequences

- The compositor learns to walk the scene graph. Today it sorts by
  z-index; tomorrow it does that within siblings, after resolving
  parent/child transforms.
- `LayerType` callers continue working unchanged; the alias maps
  deprecated values to the new enum. New code should use `LayerKind`.
- The frontend SPEC.md's "slot" string and "anchor" enum become typed
  value objects. The new SPEC-layers.md inherits the existing SPEC's
  testing conventions (Gherkin, edge cases, invariants).
- Cross-page consistency for non-character assets becomes possible
  without any new pipeline; the agent just registers a definition the
  first time a building/vehicle/named-prop appears on more than one page.
- The `stronghold` multi-tenant catalogue (ADR-035) gains a natural
  upgrade path: tenant-scoped `AssetDefinition` registries are a v2.0
  capability with the same shape.
- `PersonalizationSlot` plus `Skin` makes the BookWizard's whole
  personalisation feature one declarative pass at render time: bind
  skin → resolve world style → walk scene graph → composite. No bespoke
  per-product logic.
- This ADR adds nothing to the `stronghold` or `AgentTuring` runtimes.
  It is a `maistro-canvas`-internal change.

## Out of scope

- Implementation. Compositor, executor, routes, store, tool changes are
  follow-up ADRs.
- Database migration for existing `LayerType.OBJECT` rows. The migration
  ADR is filed alongside the v2.0 implementation work.
- Multi-language text-layer support beyond what the frontend SPEC
  already requires.
- Print-fulfilment-specific extensions (Lulu/Blurb-tuned PDF/X-1a
  metadata). Captured in a separate canvas-export ADR.
- Cross-tenant asset-definition sharing in `stronghold`.

## Source references

- `packages/maistro-canvas/src/maistro_canvas/types.py` — current
  `LayerType`, `LayerRecord`, domain errors. Extension target.
- `packages/maistro-canvas/src/maistro_canvas/protocols.py` —
  `CanvasStore`, `ImageGenClient`, `CompositorService`. Extension
  target.
- `packages/maistro-canvas/frontend/SPEC.md` — POC behavioural rules
  that informed the typed lift.
- `packages/maistro-canvas/agents/davinci/agent.yaml` — decompose-to-
  layers rule that the new taxonomy makes explicit.
- ADR-005 (Pydantic schemas), ADR-031 (front-matter), ADR-032
  (contracts), ADR-036 (ontology) — substrate.

## Links

- PR: PR #12 (originally filed) and PR resolving the ADR-039 collision
- Issue: (none)
- Follow-up ADRs: ADR-042 (compositor), ADR-043 (store), ADR-044
  (routes), ADR-045 (executor + tool) — to be filed when implementation
  begins. Bumped from ADR-040..043 due to this renumbering.
