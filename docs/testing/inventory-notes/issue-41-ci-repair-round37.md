---
inventory-delta:
  packages/maistro-canvas/tests: +0
  packages/maistro-core/tests: +0
  tests/: +0
---

# Issue #41 CI-repair round 37: PostgreSQL coverage producer replay

The reported `Coverage gate (publish-set floor + diff coverage)` failure was
rechecked against the current candidate rather than inferred from prior claims.
Using the dedicated `auto41-coverage-pg` PostgreSQL 17 service and the exact
producer environment (`MAISTRO_TEST_PG_DSN`, `MAISTRO_TEST_DATABASE_URL`, and
`MAISTRO_REQUIRE_PG_LEGS=1`), the workflow's PostgreSQL producer sequence
completed: `tests/migrations`, `alembic upgrade head`, the declared durable
core suites (including the live task-admission atomicity tests), and the Canvas
suite under branch coverage.

The durable core suite reported 5,193 passed and 92 skipped; the Canvas suite
reported 516 passed and 3 skipped. This directly exercises the migration
cleanup introduced for this coverage producer, so later durable tests run after
the migration suite has restored the shared service to head. The producer
emitted pre-existing aiosqlite thread-shutdown warnings, but no test failure.

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` also passed: 1,338 reviewed
identities at the develop-base ledger count. No test identities changed.
