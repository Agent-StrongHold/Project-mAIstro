---
inventory-delta:
  packages/maistro-canvas/tests: +38
---

# 857-canvas-scope-coverage

Thirty-eight new tests, all additions, no removals or compensating changes:

- `tests/test_routes_org_paths.py` (16): mainline bodies of the org-scoped
  canvas v1 routes (update/archive canvas, layer CRUD/reorder, job
  cancel/accept, composite save/latest, on-demand export) that the
  #857 guard refactor rewired but no test executed.
- `tests/test_asset_routes.py` (+5): book update mainline + foreign-org
  claim refusal, store-error → HTTP error mapping for sheets/profiles,
  and the render-plan book/profile/definition resolution branches.
- `tests/test_asset_executor_and_tool.py` (+1): the executor's
  fail-closed guard against an empty org scope.
- `tests/test_store_scope_conformance.py` (+16 collected: 6 dual-leg
  in-memory/PostgreSQL arcs ×2 + 4 PostgreSQL-leg canvas-store arcs):
  success arcs the refusal tests never reached (definition update,
  sheet regeneration, book create/update guards) and PG canvas
  update/job paths.

Verified +38 = collected (359) vs recorded (321); every suite besides
`packages/maistro-canvas/tests` unchanged.
