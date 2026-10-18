---
inventory-delta:
  packages/maistro-core/tests: +0
---
# p0-8-store-scope-burn

Workspace cutover P0.8 (#364): burned all 31 `KNOWN_GAPS` entries in
`test_store_boundary_scope_conformance.py` by enforcing scope at the durable
store boundary when callers pass `principal_id`.

- **Workspaces / projects:** `get` and `update` / `update_defaults` consult
  workspace membership through `store_boundary` helpers.
- **Runs:** `get_run`, `get_node_run`, `get_attempt`, and `transition_run`
  delegate to `RunStoreBoundary` (wrapping `ScopedRunReader`); `create_run`
  and the `Run` model require a non-blank `actor_principal_id`.
- **Audit:** already scoped (no gaps).

+0 on the inventory job’s memory/SQLite leg count: the suite still reports 29
tests without PostgreSQL; the PostgreSQL leg (+13) remains gated on
`MAISTRO_TEST_PG_DSN` / `MAISTRO_REQUIRE_PG_LEGS`.
