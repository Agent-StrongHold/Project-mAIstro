---
inventory-delta:
  packages/maistro-core/tests: +8
---
# Issue 12 Durable Persona Store

The live Workspace Persona now has a SQLite durable implementation and a
PostgreSQL migration/store twin. These tests prove the one-Persona-per-Workspace invariant, restart recovery,
detached update snapshots, and cascade cleanup when the owning Workspace is
deleted in both durable and in-memory ownership wiring.

`test_durable_store_pg.py` runs the durable contract against live PostgreSQL
(`MAISTRO_TEST_PG_DSN`): a Persona survives the store object that wrote it, the
Workspace uniqueness key refuses a second live Persona, updates are snapshots
that persist from a fresh store, Workspace deletion purges the Persona through
the wired ownership path, the Persona migration's foreign-key cascade (renumbered
034 → 064 when develop's chain claimed the 034 slot first) removes a
Persona when the Workspace row itself is deleted, and `wire_persona_store`
selects the PostgreSQL store on a migrated pool. The leg skips without a
server and fails closed under `MAISTRO_REQUIRE_PG_LEGS`.
