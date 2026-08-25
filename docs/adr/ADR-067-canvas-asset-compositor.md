---
id: ADR-067
title: Canvas Asset Compositor — Scene Graph, Occlusion, Prompt Composition
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-09
substrate:
  - maistro-engine#ADR-039
  - maistro-engine#ADR-040
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
implements: []
related:
  - maistro-engine#ADR-019
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
history:
  - status: Proposed
    date: 2026-05-09
  - status: Implemented
  - status: Accepted
    date: 2026-08-25
    reason: "M0 strict evidence reconciliation: current acceptance evidence does not support an Implemented completion claim; implementation history remains recorded."

---

# ADR-067: Canvas Asset Compositor

## Context

ADR-039 specifies the typed scene graph; ADR-040 persists it. Nothing
yet *uses* it. The render pipeline today is the legacy
`canvas/compositor.py` which walks `LayerRecord` rows in flat z-index
order and composites pixels via PIL. The new model needs:

1. A scene graph walk that respects `parent_id + parent_socket` and
   composes transforms parent-to-child.
2. Occlusion resolution: topologically sort instances by their
   `OcclusionHint(in_front_of, behind)` constraints, raising on cycles.
3. Per-instance prompt composition: `WorldStyle ⊕ matching
   StyleVolume.partial ⊕ RenderStyle ⊕ layer prompt` (per ADR-039 §6),
   honouring `PersonalizationSlot` bindings.
4. Personalisation compilation: `PersonalizationSlot` declarations on
   instances bind to a `ChildProfile`, producing `skin_binding` dicts
   that the parent definition's `skin_set` consumes.

This ADR specifies these as pure logic. **Pixel compositing is not
re-implemented here** — the existing PIL pipeline still owns that step.
The compositor's output is a `RenderPlan`: an ordered list of
`PlannedRender`s, each with the resolved transform, the composed
prompt, and the parent chain. Downstream consumers (image pipeline,
tests, UI previews) consume the plan.

## Decision

Engine ships **`maistro_canvas.canvas.asset_compositor`**, a pure-logic
module with no PIL dependency. The legacy `compositor.py` is unchanged.

### Module surface

```python
# packages/maistro-canvas/src/maistro_canvas/canvas/asset_compositor.py

class SceneNode:
    """Tree node wrapping an AssetInstance plus children list. Built
    from a flat list by `build_scene_graph`."""

@dataclass(frozen=True)
class PlannedRender:
    instance_id: str
    parent_chain: tuple[str, ...]    # root -> instance_id
    resolved_transform: Transform    # composed parent.transform * instance.transform
    prompt: str                      # WorldStyle ⊕ Volume ⊕ Render ⊕ layer
    asset_sheet_ref: str | None      # passed to the image backend
    skin_binding: dict[str, str] | None
    z_index: int

@dataclass(frozen=True)
class RenderPlan:
    canvas_id: str
    page_index: int | None
    world_style: WorldStyle
    rendered: tuple[PlannedRender, ...]   # in render order

# Public functions
def build_scene_graph(instances: Iterable[AssetInstance]) -> list[SceneNode]: ...
def resolve_occlusion_order(instances: Sequence[AssetInstance]) -> list[AssetInstance]: ...
def compile_personalization(
    instances: Sequence[AssetInstance],
    profile: ChildProfile | None,
    *,
    registry: AssetRegistry | None = None,
) -> list[AssetInstance]: ...
def compose_prompt(
    *,
    world_style: WorldStyle,
    style_volumes: Sequence[StyleVolume],
    page_index: int | None,
    render_style: RenderStyle | None,
    base_prompt: str,
    prompt_nudge: str | None,
    skin_binding: dict[str, str] | None = None,
) -> str: ...
def plan_render(
    *,
    canvas_id: str,
    instances: Sequence[AssetInstance],
    world_style: WorldStyle,
    style_volumes: Sequence[StyleVolume] = (),
    page_index: int | None = None,
    render_style: RenderStyle | None = None,
    profile: ChildProfile | None = None,
    registry_lookup: Callable[[str], AssetDefinition | None] | None = None,
) -> RenderPlan: ...
```

### Boundary contracts

- `build_scene_graph` raises `ValueError` if `parent_id` references a
  missing instance on the same input list.
- `build_scene_graph` raises `ValueError` if the parent chain contains a
  cycle (A→B→A).
- `resolve_occlusion_order` raises `OcclusionCycleError` (ADR-039) if
  the in_front_of/behind graph has a cycle, including self-loops.
- `compile_personalization` raises `SkinBindingError` (ADR-039) when an
  instance has a `PersonalizationSlot` whose `binding` does not appear
  in the parent definition's `skin_set`.
- `plan_render` returns `PlannedRender`s in the order produced by
  `resolve_occlusion_order`, then by `z_index ASC`, then by insertion
  order within the input list. Stable.
- `compose_prompt` is total; missing fields fall back to base + nudge.

### Behavioral contracts

- **Transform composition is associative**: `T(child) =
  T(parent) ∘ T(child_local)`, applied by depth-first walk from each
  root. Roots have no parent and use their `transform` as-is.
- **Occlusion order is topological**: for any pair (A in_front_of B),
  A appears later in the rendered list than B. For (A behind B), A
  appears earlier than B.
- **Compose-prompt is deterministic**: same inputs → same output
  string. The composition order is fixed:
  `world_style → matching style_volume → render_style → base_prompt →
  prompt_nudge → skin_binding`.
- **Style volume override is page-range scoped**: a `StyleVolume` with
  `page_range=(7,9)` applies when `page_index ∈ [7, 9]`. Multiple
  matching volumes apply in declaration order (later wins).
- **Personalisation is total after compile**: every instance with a
  `PersonalizationSlot` has a non-None `skin_binding` after
  `compile_personalization`, or the call raised.
- `plan_render` is a pure function of its inputs. Same inputs → same
  output (apart from stable list ordering).

### Composition order

Per ADR-039 §6, the prompt for a single layer is:

```
prompt =  world_style.serialised
       ⊕ matching style_volumes (in declaration order, later wins, sparsely)
       ⊕ render_style.serialised
       ⊕ definition.base_prompt
       ⊕ instance.prompt_nudge
       ⊕ skin_binding rendered as "as <skin_value>"
```

The `⊕` operator is string concatenation with `; ` separators; empty
fields are skipped. The ordering is fixed so renders are reproducible.

### Personalisation

`PersonalizationSlot.binding` is a key into the `ChildProfile`. The
binding compiles into a `skin_binding` on the instance. For
`kind == "child_likeness"`, the binding name picks the skin variant in
the parent definition's `skin_set`. For `kind == "child_name"`, the
profile's `name` is interpolated into the prompt template. The
mapping table:

| `PersonalizationSlot.kind` | Source on `ChildProfile`                      |
|----------------------------|-----------------------------------------------|
| `child_name`               | `name`                                        |
| `child_likeness`           | normalised `name` (lowercase, ascii)          |
| `pronouns`                 | `pronouns`                                    |
| `companion`                | `binding` value, no profile field             |
| `pet`                      | `binding` value, no profile field             |
| `gift`                     | `binding` value, no profile field             |
| `place_name`               | `binding` value, no profile field             |

`compile_personalization` does not touch the `ChildProfile` itself; it
produces a new `AssetInstance` with `skin_binding` populated.

## Consequences

- ADR-042 (routes) gets a single function (`plan_render`) to call when
  building the response for `GET /canvases/{id}/plan`.
- ADR-043 (executor + tool) wires `plan_render` into the agent's
  rendering decision: the agent submits a request, the executor calls
  `plan_render`, and feeds the resulting `PlannedRender`s into the
  image-generation backend.
- The existing PIL `compositor.py` is unchanged; it continues to assemble
  pixels for `LayerRecord` flat rows. A future ADR can teach it to
  consume `RenderPlan` directly.
- The compositor is **PIL-free**, so it is testable on any environment
  (no image libs required in CI). All tests run in
  `packages/maistro-canvas/tests/` alongside the asset_store tests.

## Out of scope

- Pixel rendering / blending — owned by the existing PIL compositor and
  the image-generation backend.
- Layer image caching / cache-invalidation policy — separate ADR when
  generation cost becomes a constraint.
- Server-side PDF rasterisation — separate ADR for the print pipeline.
- Migration of `LayerRecord` flat rows to `AssetInstance` — separate
  ADR after #043.

## Source references

- `packages/maistro-canvas/src/maistro_canvas/layers.py` — types
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py` —
  ADR-040 persistence the compositor reads from
- `packages/maistro-canvas/src/maistro_canvas/canvas/compositor.py` —
  legacy PIL compositor

## Links

- PR: (this PR)
- Follow-up ADRs: ADR-042 (routes), ADR-043 (executor + tool)
