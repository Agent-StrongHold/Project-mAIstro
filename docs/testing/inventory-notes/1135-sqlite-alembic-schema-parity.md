---
inventory-delta:
  packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py: +2 node IDs (new file, parametrized sqlite/postgres)
---

# SQLite/Alembic schema parity for the canonical scope stores (#1135)

New parametrized comparison (sqlite, postgres) in
`packages/maistro-core/tests/workspaces/test_sqlite_alembic_schema_parity.py`.
It closes the #1135 acceptance item "a CI schema-parity check compares columns,
nullability, keys, and materially relevant constraints for SQLite
implementations that claim conformance with an Alembic-managed canonical
store".

The durable Workspace/Project scope tables ship twice: Alembic chain (012,
019, 033) for PostgreSQL, each store's own `ensure_schema()` DDL for SQLite.
The test reads **what each side actually creates** — SQLite `PRAGMA` catalogue
against an in-memory database opened by `SqliteProjectScopeStore` +
`SqliteWorkspaceStore`; PostgreSQL `information_schema`/`pg_catalog` against a
database migrated to the Alembic head — and holds both to one dialect-neutral
spec per table (`canonical_workspaces`, `canonical_workspace_memberships`,
`canonical_projects`, `canonical_project_memberships`,
`canonical_project_resources`): column sets, nullability, primary keys,
foreign keys with ON DELETE actions, unique and partial indexes (the
one-root-per-Workspace and owner-roster predicates), and the two-state CHECK
guard that stands in for PostgreSQL's `boolean` on SQLite.

CI: the existing `ci.yml` migrations job already runs
`packages/maistro-core/tests/workspaces` with a migrated PostgreSQL service and
`MAISTRO_REQUIRE_PG_LEGS: "1"`, so the PostgreSQL leg cannot silently skip
there; locally it skips without `MAISTRO_TEST_PG_DSN` /
`MAISTRO_TEST_DATABASE_URL` and the same flag turns that skip into a failure
(verified: RuntimeError without a DSN).

Evidence at authoring time (local pgvector:pg18 at Alembic head `047`):
both legs pass (`2 passed`); the first authored predicate normalization
compared PG's bare-`is_root` partial-index spelling against an explicit
`is_root=true` canonical form and failed the postgres leg — fixed by
canonicalizing both dialects' spellings to the bare column, not by relaxing
the spec (the partial unique index is still required on both sides).
