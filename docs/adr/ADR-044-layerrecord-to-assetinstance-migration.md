---
id: ADR-044
title: LayerRecord → AssetInstance Migration Plan
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
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
tests: []
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-09
---

# ADR-044: LayerRecord → AssetInstance Migration Plan

## Context

ADR-039 §9 promised a migration ADR after the implementation work
(ADR-040 store → ADR-043 tool) landed. All four implementation ADRs
are now merged. Two layer models coexist:

- **Legacy `LayerRecord`** (`store.py` + `compositor.py` + `tool.py`) —
  flat z-ordered rows with `LayerType ∈ {background, character,
  object, text}`.
- **New `AssetInstance`** (`asset_store.py` + `asset_compositor.py` +
  `asset_routes.py` + `asset_tool.py`) — typed scene graph with
  sockets, the 7-kind `LayerKind`, parent_id + parent_socket,
  occlusion DAG, world style, asset sheets, and personalisation.

Production callers (canvas-studio-poc, davinci agent) are still on the
legacy model. The new model has no live data. We need a sequenced
migration so callers move at their pace without forcing a flag day.

## Decision

Migration runs in **four phases** over ~6 weeks. Each phase ships as
its own PR; the ADR is the contract.

### Phase 1 — Coexistence (this is where we are)

Both models live. Callers choose. The legacy `canvas/tool.py`
continues to drive `LayerRecord`; the new `canvas_asset` tool drives
`AssetInstance`. No data migration; new work uses `AssetInstance`,
existing data stays in `layers`.

Done when:

- Davinci's `agent.yaml` exposes both tools (ADR-043 follow-up; lands
  with this ADR).
- Frontend opt-in: a single canvas in canvas-studio-poc can be
  designated v2 via a flag on the `canvases` row; the row's layers
  live in `asset_instances` rather than `layers`. Existing canvases
  remain v1.

### Phase 2 — Bridge (~2 weeks)

A bridge module `canvas/layer_bridge.py` translates `LayerRecord` →
`AssetInstance` on read so legacy callers can transparently consume
the new compositor. Bridge contracts:

- `to_asset_instance(LayerRecord) -> AssetInstance` is total over
  the four legacy `LayerType` values, mapping to the LayerKind set
  per ADR-039 §1's `_LAYER_TYPE_TO_KIND` table (already in
  `layers.py`).
- `LayerRecord.image_path` becomes `AssetInstance.history[0]` plus a
  fresh inline `AssetDefinition` whose `base_prompt = LayerRecord.prompt`.
- `LayerRecord.text_config` becomes a `TEXT`-kind inline definition
  with the text rendered into the prompt for the compositor's
  text-layer path (ADR-041 v1 leaves this untouched; the bridge
  preserves it).
- `LayerRecord.tier` (draft / proof) becomes a metadata key on the
  inline definition (no first-class type yet).

Done when:

- `canvas/tool.py` (legacy) routes through `layer_bridge` →
  `asset_compositor.plan_render` for read paths.
- `canvas/compositor.py` (legacy PIL pipeline) accepts a `RenderPlan`
  in addition to `list[LayerRecord]`. Both call paths yield the same
  pixels for unchanged inputs (golden-image test at the seam).

### Phase 3 — Backfill (~3 weeks)

A one-shot script copies every `layers` row into `asset_instances`
with bridge-generated inline definitions, and links the parent
`canvases` row's `book_id` (new optional column, see migration 003)
to a freshly-created `books` row carrying a default `WorldStyle`.

Backfill is **idempotent** — running twice produces the same final
state. Each migration commits to a per-canvas `migrated_at` audit
column on `canvases`; rows already migrated are skipped.

Done when:

- Backfill script runs in dry-run on production data and reports zero
  validation errors.
- Backfill script runs with `--commit` and every `layers` row has a
  matching `asset_instances` row.
- The legacy `compositor.py` is switched to read from
  `asset_instances` (via the bridge in reverse for any remaining
  callers that haven't migrated).

### Phase 4 — Sunset (~1 week)

Legacy code paths are deprecated. The `layers` and
`generation_jobs.layer_id` columns get a `deprecated_at` audit
timestamp. New work cannot write to `layers` (a new check constraint).

Done when:

- All canvases in production have `migrated_at` set.
- `canvas/tool.py` and `canvas/compositor.py` are marked
  `# DEPRECATED — see ADR-044 Phase 4` and forward calls to the
  asset_* equivalents.
- A follow-up ADR-046 schedules deletion of the legacy modules and
  the `layers` table itself, behind an opt-in flag, no earlier than
  6 weeks after Phase 4 closes.

### Migration script

`tools/canvas/migrate_layers_to_assets.py` (new):

```python
#!/usr/bin/env python3
"""ADR-044 Phase 3 backfill.

Usage:
  migrate_layers_to_assets.py --canvas-id <id>          # one canvas
  migrate_layers_to_assets.py --org-id <id>             # tenant scope
  migrate_layers_to_assets.py --all                     # all canvases
  migrate_layers_to_assets.py --dry-run                 # validate, don't write

Idempotent: reads canvas.migrated_at and skips rows already migrated.
On --commit: emits asset_instances rows + a books row with a default
WorldStyle, then sets canvas.migrated_at = now().
"""
```

The default `WorldStyle` for unbacked canvases is:

```python
WorldStyle(
    era="modern",
    realism="watercolor",
    architectural_register="cottage",
    vehicle_register="generic",
    palette_anchors=("sage", "cream", "clay"),
    fauna_realism="cute",
)
```

Choices made: human-reviewable via the `metadata.role` heuristic
already in `_LAYER_TYPE_TO_KIND` (OBJECT → PROP unless explicitly
flagged STRUCTURE). FX, VEHICLE, and HAND_PROP layers cannot be
auto-generated from `LayerType`; the script emits a CSV report of
ambiguous rows and the operator promotes them by hand.

## Boundary contracts

- `to_asset_instance(legacy)` is total over `LayerType.{BACKGROUND,
  CHARACTER, OBJECT, TEXT}`; raises on any other value.
- The bridge preserves z_index ordering across translation.
- Backfill inserts only — never updates existing `asset_instances`
  rows. If a row already exists with the same canvas_id +
  legacy_layer_id, the script raises and exits non-zero.
- Phase 4 check constraint `CHECK (layers.deprecated_at IS NULL OR
  /* read-only */)` is implemented as a TRIGGER raising on INSERT /
  UPDATE after the deprecation timestamp.

## Behavioural contracts

- A canvas with `migrated_at` set MUST render identically to its
  pre-migration self for any prompt / seed / tier combination, given
  the same `WorldStyle` (golden-image test pinned at HEAD~Phase-3 vs
  HEAD).
- Running the backfill script twice produces zero new rows on the
  second run.
- The bridge is **lossy in one direction only**: legacy → new is
  total; new → legacy is partial (no place to put `parent_id`,
  `parent_socket`, `occlusion`, `personalization`, `skin_binding`).
  Reverse-translation is not provided; callers wanting to read the
  new model do so via the new compositor.

## Consequences

- Davinci's prompt iteration can use both tools during Phase 1; we
  watch which tool the agent reaches for and use that signal to time
  Phase 4.
- canvas-studio-poc's POC frontend is already using the legacy shape
  (JSONB blobs, not `layers` rows directly); ADR-045 covers its own
  cutover separately. This ADR is engine-internal.
- The `frontend/SPEC.md` invariant "Once an image appears in a
  layer, it is never overwritten without being pushed to history[]"
  applies under the new model via `AssetInstance.history`. The
  bridge preserves it.

## Out of scope

- Cross-tenant migration policy — Stronghold's multi-tenant
  catalogue follows from ADR-035; not affected here.
- Performance benchmarking the new compositor at scale — separate
  ADR if a regression appears.
- Removing the legacy schema (the `layers` table itself) — ADR-046
  follow-up after Phase 4 settles.

## Source references

- `packages/maistro-canvas/src/maistro_canvas/canvas/store.py` (legacy)
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py` (new)
- `packages/maistro-canvas/src/maistro_canvas/canvas/compositor.py` (legacy)
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_compositor.py` (new)
- `packages/maistro-canvas/src/maistro_canvas/layers.py` `_LAYER_TYPE_TO_KIND`
- `alembic/versions/002_canvas_asset_039.py`

## Links

- PR: (this PR)
- Follow-up ADRs: ADR-046 (legacy schema removal, post-Phase 4)
