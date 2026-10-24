---
id: SPEC-221
title: "Canvas asset executor and agent tool surface"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-039
  - maistro-engine#ADR-040
  - maistro-engine#ADR-041
  - maistro-engine#ADR-043
implements:
  - maistro-engine#ADR-043
related:
  - maistro-engine#SPEC-219
  - maistro-engine#SPEC-220
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-canvas/tests/test_asset_executor_and_tool.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-221: Canvas asset executor and agent tool surface

## Context

The davinci agent's only canvas integration was the legacy in-process
`canvas/tool.py`, speaking the flat `LayerRecord` shape. To exercise the
new ADR-041 asset model, the agent needed a JSON-serialisable tool surface
plus an orchestrating executor that walks the asset store, the compositor,
and the `ImageGenClient` for a single tool call. ADR-043 decided to ship
`asset_executor.py` and `asset_tool.py` as pure-Python modules, testable
without network or PIL via a `FakeImageGenClient`, registered alongside
(not replacing) the legacy tool.

## Goals

- `AssetExecutor`: a façade coordinating `AssetStore` + `ImageGenClient`
  for definition/instance CRUD, sheet generation/regeneration, render
  planning, and page rendering.
- `AssetTool`: a stateless, action-dispatching tool surface
  (`call(action, args) -> dict`) mirroring the legacy tool's structure so
  `agents/davinci/agent.yaml` can register it with no prompt-engineering
  surprises.
- Davinci registers both the legacy `canvas` tool and the new
  `canvas_asset` tool, preferring the new one for `LayerKind` work.

## Non-goals

- Rate limiting / retries against the image backend — handled at the
  `ImageGenClient` level.
- Parallel `render_page` execution — sequential per-instance by design,
  for predictable rate-limit behavior; parallelism is a separate future
  ADR if needed.
- Skill marketplace integration for canvas actions — separate ADR.
- Migrating davinci's prompts to discourage the legacy tool — left for
  later prompt iteration.

## Decision

`packages/maistro-canvas/src/maistro_canvas/canvas/asset_executor.py`:

```python
class AssetExecutor:
    def __init__(self, store: AssetStore, image_gen: ImageGenClient, *, sheet_size=(1024, 1024)) -> None: ...
    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition: ...
    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance: ...
    async def remove_instance(self, instance_id: str) -> None: ...
    async def generate_sheet(self, *, asset_id, refs, prompt, params=None) -> AssetSheet: ...
    async def regenerate_sheet(self, *, asset_id, prompt, refs=None, params=None) -> AssetSheet: ...
    async def plan(self, *, canvas_id, world_style, style_volumes=(), page_index=None, render_style=None, profile_id=None) -> RenderPlan: ...
    async def render_page(self, *, canvas_id, plan, size=(1024, 1024)) -> tuple[PlannedRender, list[ImageData]]: ...
```

`packages/maistro-canvas/src/maistro_canvas/canvas/asset_tool.py`:

```python
class AssetTool:
    name: str = "canvas_asset"
    def __init__(self, executor: AssetExecutor) -> None: ...
    async def call(self, action: str, args: dict[str, Any]) -> dict[str, Any]: ...
```

`call()` dispatches on `action` (`register_definition`,
`get_definition`, `list_definitions`, `upsert_instance`,
`list_instances`, `remove_instance`, `generate_sheet`,
`regenerate_sheet`, `plan`, `render_page`) with plain-dict args/returns
for the agent's JSON tool protocol, reusing the store's serialization
helpers for shape conversion. `plan` is a pure function of canvas state,
world style, profile, style volumes, and render style — same inputs,
same plan. `render_page` calls `ImageGenClient.generate(...)` once per
`PlannedRender`, sequentially, returning the parallel image list so the
agent decides which to keep. Store errors (e.g.
`AssetDefinitionNotFoundError`, `OcclusionCycleError`) propagate verbatim
through the executor and the tool.

## Acceptance criteria

- [x] `AssetExecutor` exposes definition/instance CRUD, sheet
      generate/regenerate, `plan`, and `render_page`
- [x] `AssetTool.call` dispatches purely on `action`; an unknown action
      raises `ValueError` listing valid actions
- [x] `regenerate_sheet` returns a strictly greater revision than the
      prior persisted sheet
- [x] `plan` is a pure function of its inputs (same inputs → same
      `RenderPlan`)
- [x] `render_page` is sequential per-instance, not parallel
- [x] Store errors propagate verbatim through the executor and tool
- [x] Both modules are testable without network/PIL via a
      `FakeImageGenClient`

## Testing

Covered by
`packages/maistro-canvas/tests/test_asset_executor_and_tool.py`.

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-039: External library adoption policy](../adr/ADR-039-external-library-adoption-policy.md)
- [ADR-040: Canvas Asset Store](../adr/ADR-040-canvas-asset-store.md)
- [ADR-041: Canvas Layer Taxonomy, Scene Graph, and World Style](../adr/ADR-041-canvas-layer-taxonomy-and-world-style.md)
- [ADR-043: Canvas Asset Executor and Tool](../adr/ADR-043-canvas-asset-executor-and-tool.md)
- [SPEC-219: Canvas layer taxonomy](SPEC-219-canvas-layer-taxonomy.md)
- [SPEC-220: Canvas asset store](SPEC-220-canvas-asset-store.md)
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_executor.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_tool.py`
