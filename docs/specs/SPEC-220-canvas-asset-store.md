---
id: SPEC-220
title: "Canvas asset store: definitions, sheets, instances, profiles, books"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-005
  - maistro-engine#ADR-031
  - maistro-engine#ADR-032
  - maistro-engine#ADR-040
  - maistro-engine#ADR-041
implements:
  - maistro-engine#ADR-040
related:
  - maistro-engine#SPEC-219
  - maistro-engine#SPEC-221
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-canvas/tests/test_asset_store.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-220: Canvas asset store: definitions, sheets, instances, profiles, books

## Context

ADR-041 shipped the typed scene-graph layer model as contracts only — no
persistence. Without a store, the davinci agent and any future FastAPI
surface had no way to load or save `AssetDefinition`s, asset sheets,
`AssetInstance`s, `ChildProfile`s, or the book-level `WorldStyle`. The
pre-existing `store.py` persists the deprecated flat `LayerRecord` shape,
not the new model. ADR-040 decided to ship a sibling
`asset_store.py` implementing the ADR-041 protocols, coexisting with the
legacy store during migration.

## Goals

- `InMemoryAssetStore` and `PostgresAssetStore`, both implementing the
  same async CRUD surface for `AssetDefinition`, `AssetSheet`,
  `AssetInstance`, `ChildProfile`, and `Book`.
- Idempotent `register_definition` — re-registering identical fields is a
  no-op; differing fields raise.
- Monotonic, atomic `regenerate_sheet` revision bumping.
- Org-scoped instance listing via the existing `org_id` column
  convention.
- `remove_instance` orphans (not deletes) child rows via `parent_id`
  cascade to `NULL`.

## Non-goals

- Image rendering / compositing — separate compositor module.
- HTTP routes — separate routes module.
- Agent / tool integration — covered by SPEC-221.
- Migrating existing `LayerRecord` rows to `AssetInstance` — deferred to
  a future data-migration ADR.

## Decision

`packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`:

```python
class InMemoryAssetStore:
    """Ephemeral test store."""

class PostgresAssetStore:
    """Production store. Raw SQL via sqlalchemy text(), async."""

# Both expose:
async def register_definition(self, defn: AssetDefinition) -> AssetDefinition
async def get_definition(self, asset_id: str) -> AssetDefinition | None
async def list_definitions_by_kind(self, kind: str) -> list[AssetDefinition]
async def update_definition(self, defn: AssetDefinition) -> AssetDefinition
async def upsert_sheet(self, sheet: AssetSheet) -> AssetSheet
async def get_sheet(self, asset_id: str) -> AssetSheet | None
async def regenerate_sheet(self, asset_id, sheet_image, refs=None, params=None) -> AssetSheet
async def upsert_instance(self, instance: AssetInstance) -> AssetInstance
async def get_instance(self, instance_id: str) -> AssetInstance | None
async def list_instances(self, canvas_id: str) -> list[AssetInstance]
async def remove_instance(self, instance_id: str) -> None
async def upsert_profile(self, profile: ChildProfile) -> ChildProfile
async def get_profile(self, profile_id: str) -> ChildProfile | None
async def create_book(self, *, book_id, title, world_style, style_volumes=(), profile_id=None) -> Book
async def get_book(self, book_id: str) -> Book | None
async def update_book(self, book: Book) -> Book
```

Postgres tables: `asset_definitions`, `asset_sheets`, `asset_instances`
(with a `CHECK` constraint enforcing exactly one of `definition_id` /
`inline_definition`), `child_profiles`, `books`. The pre-existing
`canvases` table is unchanged in this spec.

`register_definition` compares canonical fields on re-registration: an
identical definition is a no-op; a differing one raises `ValueError`.
`regenerate_sheet` increments `revision` atomically (`SELECT ... FOR
UPDATE` in the Postgres store) so concurrent regenerations on the same
`asset_id` can't produce duplicate revision numbers. `list_instances`
orders by `(z_index ASC, created_at ASC)`. `remove_instance` sets
`parent_id` to `NULL` on child rows rather than deleting them.

## Acceptance criteria

- [x] `register_definition(D); register_definition(D)` leaves exactly one
      row for `D.asset_id`
- [x] `register_definition` with differing fields for an existing
      `asset_id` raises
- [x] `regenerate_sheet` produces a strictly increasing `revision`
- [x] `upsert_instance` validates an inline definition against the same
      schema as a registered one
- [x] `list_instances(canvas_id)` returns instances ordered by
      `(z_index, created_at)`
- [x] `remove_instance` orphans child rows (sets `parent_id` to `NULL`)
      rather than deleting them
- [x] Both `InMemoryAssetStore` and `PostgresAssetStore` expose the same
      method surface

## Testing

Covered by
`packages/maistro-canvas/tests/test_asset_store.py`.

## Open questions

- None — design is implemented and stable as of this writing.

## References

- [ADR-040: Canvas Asset Store](../adr/ADR-040-canvas-asset-store.md)
- [ADR-041: Canvas Layer Taxonomy, Scene Graph, and World Style](../adr/ADR-041-canvas-layer-taxonomy-and-world-style.md)
- [SPEC-219: Canvas layer taxonomy](SPEC-219-canvas-layer-taxonomy.md)
- `packages/maistro-canvas/src/maistro_canvas/canvas/asset_store.py`
