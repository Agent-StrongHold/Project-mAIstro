---
inventory-delta:
  packages/maistro-core/tests: +38
---
# Issue 12 Durable Persona Store

The live Workspace Persona now has a SQLite durable implementation and a
PostgreSQL migration/store twin. These tests prove the one-Persona-per-Workspace invariant, restart recovery,
detached update snapshots, and cascade cleanup when the owning Workspace is
deleted in both durable and in-memory ownership wiring.

Repair round (CI gates at ac7f24274a49) added four tests here and two on the
PostgreSQL leg, all named regressions or review findings:

- `test_wired_workspace_delete_takes_its_persona_in_the_same_transaction` —
  the P1 the wiring alone hid: with the Persona store attached the way
  `create_container` wires it, a Persona delete that opens its own
  `BEGIN IMMEDIATE` fails every wired SQLite workspace deletion with
  "cannot start a transaction within a transaction". The delete now rides
  the caller's transaction (`delete_for_workspace_in`).
- `test_a_failed_workspace_delete_rolls_the_persona_back_with_it` (SQLite
  and PostgreSQL twins) — the Persona delete is inside the Workspace delete
  transaction, so a Project-purge failure restores the Persona instead of
  pairing a surviving Workspace with a deleted one.
- `test_a_failed_in_memory_delete_restores_the_workspace_and_its_persona` —
  the compensation contract across both ownership boundaries in the
  reference store.
- `test_non_finite_persona_payload_survives_a_sqlite_round_trip` and
  `test_a_non_finite_persona_payload_survives_the_jsonb_round_trip` — the
  lossless evidence codec on both durable backends; NaN comes back as NaN,
  not `null` (#132 review finding, same mechanism the Run spine uses).
- `test_the_wired_workspace_delete_needs_no_second_connection` — a
  one-connection pool proves the PostgreSQL delete joins the ambient
  transaction instead of acquiring a second pooled connection (a size-1
  pool deadlocks under the old shape; pytest-timeout is the alarm).
- `test_a_lost_create_race_is_the_domain_error_not_the_driver_s` — an
  insert-after-check race surfaces as `WorkspacePersonaAlreadyExists`, not
  a raw `asyncpg.UniqueViolationError`.
- `test_a_naive_timestamp_is_read_as_utc_never_host_local` (`test_store.py`) —
  a pre-awareness naive timestamp validates to UTC, so a legacy payload reads
  as the instant that was written on any host (#1149's timezone rule).

The same repair round then closed the coverage the diff gate would have
scored: the new Persona modules measured 52–88% because the store contracts
below them were pinned only on the in-memory twin. The equivalence set now
pins each boundary on every backend (memory, SQLite, PostgreSQL), and the
backend-selection wiring on its own:

- duplicate persona id → `PersonaAlreadyExists`; absent-id update and delete →
  `PersonaNotFound`; re-parent into an occupied Workspace →
  `WorkspacePersonaAlreadyExists` with the Persona restored on its old
  Workspace (durable twins roll back; the reference store never moves it).
- a re-parent update frees the Workspace it left (the successor Persona can
  be created there); `delete_for_workspace` and `delete_for_workspace_in`
  purge by Workspace directly — the in-variant entry point the wired
  Workspace delete uses.
- the PostgreSQL id race (`test_a_lost_create_race_on_the_persona_id_is_the
  _domain_error`) mirrors the Workspace race onto the primary key, and a
  violation on any foreign constraint keeps the driver's error identity
  (fake-pool translation test; a real foreign-key race is unreachable on a
  two-constraint table).
- `wire_persona_store` selects SQLite (creating its schema), falls back to
  memory beside the reference Project store, and refuses PostgreSQL without
  a pool or without the migrated `canonical_personas` tables with
  `ConfigError` — matching durability is a configuration error, not a
  silent fallback.

`test_durable_store_pg.py` runs the durable contract against live PostgreSQL
(`MAISTRO_TEST_PG_DSN`): a Persona survives the store object that wrote it, the
Workspace uniqueness key refuses a second live Persona, updates are snapshots
that persist from a fresh store, Workspace deletion purges the Persona through
the wired ownership path, the Persona migration's foreign-key cascade (renumbered
034 → 064 when develop's chain claimed the 034 slot first) removes a
Persona when the Workspace row itself is deleted, and `wire_persona_store`
selects the PostgreSQL store on a migrated pool. The leg skips without a
server and fails closed under `MAISTRO_REQUIRE_PG_LEGS`.
