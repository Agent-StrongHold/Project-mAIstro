---
inventory-delta:
  added: []
  removed: []
  modified:
    - tests/migrations/test_migration_chain.py::empty_database
  rationale: >
    Fixture repair for a reproduced shared-DB ordering failure; no net test
    count change (11 tests before and after), so no new coverage is claimed.
    The fixture now drops every table in `public` at setup and teardown
    instead of only `alembic downgrade base`, because standalone-path stores
    (`pg_strikes._SCHEMA` and siblings) create chain-owned tables with
    `CREATE TABLE IF NOT EXISTS` outside the chain and one suite poisoned the
    next ("relation security_strikes already exists" in migration 005).
---

# auto-72 verifier repair 4 — migration-chain fixture is order-independent

## Evidence

Reproduced against a live pgvector:pg18 (`auto-72-pg`, db `maistro`) at head
0baf1eb226074110a178deca2090c2f536264d87 before the fix:

1. `drop schema public cascade; create schema public` (pristine)
2. `uv run pytest tests/migrations/test_migration_chain.py -q` → 11 passed
   (teardown leaves `alembic_version` at base)
3. `uv run pytest packages/maistro-core/tests/security/test_strike_tracker_conformance.py -q`
   → 40 passed (standalone `db_url` path raw-DDLs `security_strikes`,
   `security_violations`, `security_rate_limits`)
4. `uv run pytest tests/migrations/test_migration_chain.py -x -q` → **FAILED**
   `test_upgrade_head_succeeds_on_an_empty_database` (returncode 1 in 005,
   create_table security_strikes)

After the fixture repair, the same sequence passes:

- step 4 rerun on the poisoned DB: 11 passed
- strikes → migrations again: 40 passed + 11 passed
- migrations teardown now leaves zero tables; the strike suite recreates its
  own tables on connect (40 passed immediately after a migrations teardown)

## Why drop-all is safe

- Chain tables were already destroyed by `downgrade base`; the fixture only
  stops pretending runtime-created tables are not there.
- Runtime stores bootstrap with `CREATE TABLE IF NOT EXISTS` on connect, so
  nothing that runs later on the shared DB is stranded.
- Identifiers are quoted catalog values; drops are `IF EXISTS ... CASCADE`.
