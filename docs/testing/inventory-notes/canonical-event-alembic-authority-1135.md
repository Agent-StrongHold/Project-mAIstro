---
inventory-delta:
  packages/maistro-core/tests: +9
---
# Canonical Event schema authority (#1135, partial)

Five new unit cases cover missing uniqueness guarantees (three), acceptance of
additive migration indexes, and fail-closed wiring even when another backend is
supplied. Existing startup tests now require read-only checks instead of DDL.

Four new PostgreSQL cases cover a real revision-030 schema under a disposable
DML-only role (startup, idempotency, restart and a second replica), and refusal
of missing table, missing column and missing unique-key shapes. The fixtures
render and execute the official Alembic revision, not a duplicate table schema.
The existing PostgreSQL Event ordering/projection tests use that same fixture.

The PostgreSQL cases skip locally without MAISTRO_TEST_DATABASE_URL. Existing
CI durable-events and coverage (PostgreSQL) jobs collect this directory and set
MAISTRO_REQUIRE_PG_LEGS, which turns missing service configuration into failure.
No test identity is removed; two existing test names now describe read-only
schema validation. This slice does not close #1135 or remove other runtime DDL.
