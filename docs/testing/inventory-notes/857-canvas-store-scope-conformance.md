---
inventory-delta:
  packages/maistro-canvas/tests: +49
---

# Two-tenant scope conformance for the Canvas and Asset stores (#857, #816)

Lane `m2-857-lane` (commit b40765b3 plus this session's completion). The
Defect Ladder found that mutations dropping `org_id` survived the whole
Canvas suite because nothing ever ran the durable stores against two orgs
and asked whether one could see the other's rows.

**+49** in `test_store_scope_conformance.py` (new). One file, three
layers:

- **19 store-behavior arcs** (14 asset + 13 canvas tests; the asset body
  is parametrized over `inmemory`/`postgres` legs, so 26 of the 49 are
  the PostgreSQL flavour, skipped without `MAISTRO_TEST_PG_DSN` and
  failing instead when `MAISTRO_REQUIRE_PG_LEGS` is set). Cross-tenant
  reads must be *absence* — `None`/`NotFound` — never the row and never a
  403-shaped confirmation. Writes isolate: org B cannot update, shadow,
  or re-scope org A's rows by id, and a body-provided `org_id` is a
  selection, never an authority.
- **8 route arcs** (new this session): the `/v2/canvas` HTTP edge
  resolves the tenant from the authenticated principal — two principals
  share one router/store, org B's view of org A's rows is 404 — plus
  unauthenticated rejection (no token 401, wrong token 401, unconfigured
  deployment fails closed 503) before any store access.
- **3 static ratchets**: the source-level arcs that run without a server,
  failing the day an ID-addressed query in `PgCanvasStore` loses its org
  predicate, the day the protocol grows a defaulted `org_id`, or the day
  a job receipt stops carrying its scope.

The in-memory asset legs run always — a fixture bug in the first draft
pulled the PostgreSQL engine into the in-memory leg and silently skipped
it; fixed in the same session. Six existing test files
(`test_asset_store.py`, `test_executor.py`,
`test_canonical_executor_integration.py`,
`test_asset_executor_and_tool.py`, `test_job_runner_lifecycle.py`,
`test_migration_parity.py`) were rewritten in b40765b3 for the
keyword-only `org_id` signatures with counts unchanged.
