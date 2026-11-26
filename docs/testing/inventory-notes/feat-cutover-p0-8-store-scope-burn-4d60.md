---
inventory-delta:
  packages/maistro-core/tests: +30
---
# feat-cutover-p0.8-store-scope-burn (#1841) — diff-coverage repair

Follow-up on #1841 after the Coverage gate failed on six changed production
files (`store_boundary.py`, workspace/run stores, `legacy_archive.py`) and
the root `test` job failed suite inventory.

## Why the tests were added

- `test_store_boundary_gates.py` — unit coverage for blank-principal and
  workspace-denial paths in `workspaces/store_boundary.py`.
- `test_store_boundary.py` — `RunStoreBoundary` success/refusal paths and
  `require_admitted_actor` validation in `runs/store_boundary.py`.
- `test_store_boundary_scope_conformance.py` — parametrized blank-principal
  get/update denials across memory, sqlite, and postgres workspace stores.
- `test_legacy_archive.py` — both branches of legacy actor backfill in
  `_reproduce()`.

## Test deltas

| Suite | Δ | Source |
|-------|---|--------|
| `packages/maistro-core/tests` | +30 | four files above (parametrize expands backend legs) |
