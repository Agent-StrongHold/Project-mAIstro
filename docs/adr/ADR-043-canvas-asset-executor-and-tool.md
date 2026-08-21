---
id: ADR-043
title: Canvas Asset Executor and Tool — Agent Integration
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-09
substrate:
  - maistro-engine#ADR-039
  - maistro-engine#ADR-040
  - maistro-engine#ADR-041
  - maistro-engine#ADR-042
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
  - packages/maistro-canvas/tests/test_asset_executor_and_tool.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-09
---

# ADR-043: Canvas Asset Executor and Tool

## Context

ADR-039 → ADR-042 deliver the canvas asset model end-to-end: types,
persistence, scene-graph compositor, HTTP routes. The davinci agent
still uses the legacy in-process `canvas/tool.py`, which speaks
`LayerRecord` flat rows. To exercise the new model, the agent needs:

1. A **tool surface** the agent can call (matching the existing tool's
   name + structure so `agents/davinci/agent.yaml` registers it
   alongside the legacy tool with no prompt-engineering surprises).
2. An **executor** that orchestrates the asset store, the compositor,
   and the `ImageGenClient` so a single tool call walks the whole
   pipeline: validate → plan → generate → persist.

## Decision

Engine ships two new modules in `packages/maistro-canvas/`:

```
src/maistro_canvas/canvas/asset_executor.py   # action coordinator
src/maistro_canvas/canvas/asset_tool.py       # agent-facing tool surface
```

Both are pure-python, testable without a network or PIL. Image
generation is mocked through the `ImageGenClient` protocol; a
`FakeImageGenClient` fixture is provided for tests.

### `asset_executor.AssetExecutor`

Coordinates a set of high-level actions on the asset store:

```python
class AssetExecutor:
    def __init__(
        self,
        store: AssetStore,
        image_gen: ImageGenClient,
        *,
        sheet_size: tuple[int, int] = (1024, 1024),
    ) -> None: ...

    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition: ...
    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance: ...
    async def remove_instance(self, instance_id: str) -> None: ...

    async def generate_sheet(
        self,
        *,
        asset_id: str,
        refs: tuple[str, ...],
        prompt: str,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet: ...

    async def regenerate_sheet(
        self,
        *,
        asset_id: str,
        prompt: str,
        refs: tuple[str, ...] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet: ...

    async def plan(
        self,
        *,
        canvas_id: str,
        world_style: WorldStyle,
        style_volumes: tuple[StyleVolume, ...] = (),
        page_index: int | None = None,
        render_style: RenderStyle | None = None,
        profile_id: str | None = None,
    ) -> RenderPlan: ...

    async def render_page(
        self,
        *,
        canvas_id: str,
        plan: RenderPlan,
        size: tuple[int, int] = (1024, 1024),
    ) -> tuple[PlannedRender, list[ImageData]]: ...
```

The executor is the agent's friendly façade: every action validates,
calls the store, and (for sheet/page generation) routes to
`ImageGenClient.generate(...)` with the conditioning args from
ADR-039 §11.

### `asset_tool.AssetTool`

Stateless tool surface the agent invokes. Mirrors the legacy
`canvas/tool.py` structure (one method per action, JSON-serialisable
args/returns):

```python
class AssetTool:
    name: str = "canvas_asset"
    description: str = "ADR-039 canvas asset model — definitions, instances, sheets, plans"

    def __init__(self, executor: AssetExecutor) -> None: ...

    async def call(self, action: str, args: dict[str, Any]) -> dict[str, Any]: ...
```

`call(...)` dispatches on `action`:

| Action                 | Args                                                  | Returns          |
|------------------------|-------------------------------------------------------|------------------|
| `register_definition`  | `definition`                                          | `definition`     |
| `get_definition`       | `asset_id`                                            | `definition`     |
| `list_definitions`     | `kind`                                                | `[definition]`   |
| `upsert_instance`      | `instance`                                            | `instance`       |
| `list_instances`       | `canvas_id`                                           | `[instance]`     |
| `remove_instance`      | `instance_id`                                         | `{ok: true}`     |
| `generate_sheet`       | `asset_id, refs, prompt, params?`                     | `sheet`          |
| `regenerate_sheet`     | `asset_id, prompt, refs?, params?`                    | `sheet`          |
| `plan`                 | `canvas_id, world_style, ...`                         | `render_plan`    |
| `render_page`          | `canvas_id, plan, size?`                              | `[planned, imgs]`|

Every action argument and return is a plain dict suitable for the
agent's JSON tool protocol. The tool reuses the `_ser_*`/`_deser_*`
helpers from ADR-040 for shape conversion.

### Davinci agent registration

`packages/maistro-canvas/agents/davinci/agent.yaml` gains
`canvas_asset` in its `tools:` list alongside the existing `canvas`
tool. A short rule is added so the agent prefers the new tool when
working with `LayerKind` (the new taxonomy) and the old tool when
working with `LayerType` (the legacy four-value enum). This lets both
flows coexist during the migration.

### Boundary contracts

- `register_definition` is idempotent at the store level (ADR-040);
  the tool surface mirrors that behaviour without re-implementing it.
- `generate_sheet` / `regenerate_sheet` always return the persisted
  `AssetSheet` row (revision included). On regeneration, the new
  revision is strictly greater than the prior.
- `plan` is a pure function of (canvas state, world style, profile,
  style volumes, render style) — same inputs, same plan. Wrapped from
  `asset_compositor.plan_render`.
- `render_page` calls `ImageGenClient.generate(...)` once per
  `PlannedRender`; the tool returns the parallel list of images so
  the agent can decide which to keep / retry. Persistence of choices
  is the agent's job (via subsequent `upsert_instance` calls).

### Behavioural contracts

- `AssetTool.call` dispatches purely on `action`; unknown actions
  raise `ValueError` with a list of valid actions.
- `AssetExecutor.render_page` is sequential per-instance — easy to
  read, easy to cancel, predictable rate-limit behaviour against the
  image backend. A future ADR can introduce parallelism with
  `asyncio.gather`.
- Errors from the store (e.g. `AssetDefinitionNotFoundError`,
  `OcclusionCycleError`) propagate verbatim through the executor and
  the tool. The HTTP route in ADR-042 maps them; the agent runtime
  can do the same on the JSON edge.

## Consequences

- The davinci agent gains a real handle on the new model without a
  rewrite — it loads both tools and picks per task.
- The Canvas Studio frontend's Express → FastAPI cutover becomes
  straightforward: the frontend talks to the ADR-042 routes, which
  call into the same executor the agent uses.
- The existing `canvas/tool.py` is unchanged; it continues to drive
  the legacy `LayerRecord` flow until the migration ADR consolidates
  them.

## Out of scope

- Rate limiting + retries on the image backend — handled at the
  `ImageGenClient` level, not the executor.
- Parallel `render_page` execution — separate ADR if a real
  performance regression appears.
- Skill marketplace integration (`maistro.skills`) — separate ADR
  when canvas actions become marketplace-shareable.
- Migrating davinci's prompts to discourage the legacy tool — left
  for the prompt iteration once the new flow proves out.

## Source references

- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_compositor.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_routes.py`
- `packages/maistro-canvas/src/maistro_canvas/canvas/tool.py` —
  legacy in-process tool, unchanged.
- `packages/maistro-canvas/agents/davinci/agent.yaml` — tool roster.

## Links

- PR: (this PR)
- Follow-up: BookWizard frontend's Express → FastAPI cutover, then a
  data-migration ADR consolidating `LayerRecord` → `AssetInstance`.
