---
inventory-delta:
  packages/maistro-core/tests: +3
---

# Issue #13 repair round — the audit table the container's wiring creates

CI-repair round for the `durable-events` / `integration-scope` gates on the
`auto-13` branch (head `9d8d7e96f`, base `e20e9f52e`).

## The defect

`PgAuditLog.ensure_schema()` only ever *altered* `audit_log`; it never created
it. Since #2198 (`d32ddff76`) the container calls it unconditionally when a
PostgreSQL pool is present (`packages/maistro-core/src/maistro/container.py`,
`_wire_audit_log`), so a container wired against a database that has not run
the migration chain died on startup with

```
asyncpg.exceptions.UndefinedTableError: relation "audit_log" does not exist
```

before the durable event stores were even reached. The `durable-events` CI job
is the only job that wires a container against an unmigrated PostgreSQL
database, and all five of its PostgreSQL legs failed there.

## The repair

`packages/maistro-core/src/maistro/persistence/pg_audit.py` now creates the
table when it is missing, under the same bootstrap discipline
`ensure_event_schema` gives the durable event stores: a transaction-scoped
advisory lock (`pg_advisory_xact_lock`) serialises concurrent workers, so two
of them cannot both run the DDL and lose the `pg_type_typname_nsp_index`
race. The table's shape is the one the migration chain builds (005 plus 036's
`org_id`), the ADR-073 proof columns are still added with the idempotent
`ADD COLUMN IF NOT EXISTS` form, and the scope index from 036 is created too.
The SQLite sibling (`sqlite_audit.py`) already bootstrapped its table this
way; the two stores now agree.

## The tests (+3 node IDs)

- `packages/maistro-core/tests/events/test_container_pg_durable_events.py` —
  `TestTheAuditStoreComesUpToo`: two PostgreSQL legs that wire a container
  against a database whose `audit_log` was dropped, and prove the audit store
  is a `PgAuditLog` that writes and reads back a signed decision. Without the
  repair both fail with the production `UndefinedTableError` above.
- `packages/maistro-core/tests/persistence/test_pg_audit.py` — the
  `ensure_schema` test now asserts the bootstrap (one `CREATE TABLE IF NOT
  EXISTS audit_log` carrying every column the store writes, plus the
  idempotent column upgrades) and a second test asserts the advisory lock is
  taken before the DDL.
- `packages/maistro-core/tests/test_container_wiring.py` — the wiring test's
  expected statement list follows the new bootstrap.

## Evidence

- `MAISTRO_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/maestro_test
  MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests/events`
  → `385 passed` on an unmigrated PostgreSQL 17 (before the repair: 5 failed,
  `relation "audit_log" does not exist`).
- The same suite against a database carrying the migration chain's `audit_log`
  shape (nullable `org_id`, the 005/036 indexes) → `383 passed, 2 deselected`
  — the bootstrap is a no-op on a migrated table.
- The bootstrapped table's columns match the migration-built table column for
  column (`information_schema.columns` diff over `maestro_boot` and
  `maestro_mig`), except that the fresh table makes `org_id` `NOT NULL` — the
  SQLite sibling's shape — where migration 036 leaves it nullable for rolling
  deploys.
- Reverting only the `CREATE TABLE` line makes the two new legs fail with
  `UndefinedTableError: relation "audit_log" does not exist`, so they fail
  against the regression they name.
