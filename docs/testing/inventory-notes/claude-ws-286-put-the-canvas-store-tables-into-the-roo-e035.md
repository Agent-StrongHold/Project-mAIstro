---
inventory-delta:
  packages/maistro-canvas/tests: +8
---
# claude-ws-286-put-the-canvas-store-tables-into-the-roo-e035

`packages/maistro-canvas/tests` gains 8 node IDs, all in the new
`test_canvas_store_migration.py`; nothing was removed or renamed (#286).

- 2 static tests, no server: every table `PgCanvasStore` names in its SQL is
  left behind by the root alembic chain's upgrades, and the reader that finds
  those tables is pinned to exactly the five Canvas tables so it cannot pass
  vacuously.
- 6 PostgreSQL legs (skip without `MAISTRO_TEST_PG_DSN`, fail under
  `MAISTRO_REQUIRE_PG_LEGS`), each in a throwaway database of its own:
  `upgrade head` from empty then a real store round trip (canvas, layers,
  reorder, removal with re-pack, job create/claim/fenced update, composite,
  blob); re-applying 044 over existing tables keeps their rows; adopting a
  hand-made pre-044 schema (no lease columns, no `canvas_blobs`); adopting a
  standalone unique index without duplicating it; `downgrade`; and the
  partial pending-claim index.

`tests/migrations/test_migration_chain.py` keeps its count: its
`EXPECTED_TABLES` set gains the five tables, no test is added.
