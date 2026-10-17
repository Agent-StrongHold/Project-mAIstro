---
inventory-delta:
  tests/: +6
---
# Issue #41 CI repair: scope the migration conftest restore to servers that can apply the chain

## What moved and why

`tests/migrations/conftest.py` restores the configured PostgreSQL service to
Alembic head at session finish so durable suites that follow the migration
tests against the same service start from a real schema. That restore walks
the chain from 001, and 001 opens with `CREATE EXTENSION IF NOT EXISTS
vector` — which the `durable-events` CI job's plain `postgres:17` service
cannot serve. Run 37472873061 failed that job through `pytest.fail` at
session finish (`conftest.py:56`) even though every test in the session had
passed: the events suite 382/382, the schema-agreement suite 5/5. The same
red cascaded into the `integration-scope` aggregator, which requires
`durable-events` to conclude success.

The hook now probes 001's first statement inside a rolled-back transaction
and skips the restore when the server cannot apply it. Jobs with a
pgvector-capable service (ci.yml `postgres`, the quality.yml coverage
producer) are unaffected: locally the whole `tests/migrations` directory was
run against a fresh pgvector-capable database and the session finish still
restored head (`058`), with `alembic upgrade head` idempotent afterwards and
the durable events suite passing against the restored schema.

## The tests

`tests/migrations/test_migration_conftest_restore.py` pins the contract:
the skip (nothing dropped, no alembic run) where the chain cannot apply and
where no URL is configured; the loud `pytest.fail` when a capable server's
head upgrade fails; a coupling pin asserting 001 still contains the probed
statement; and, against a live server, that a capable URL classifies as
applicable and that the probe leaves a fresh `template0` database without
the extension (the rolled-back CREATE does not leak).

## Validation evidence

- Pre-fix failure reproduced deterministically on a non-superuser-owned
  `template0` database (pgvector is not `trusted`): `alembic upgrade head`
  exits 1 with the extension error — the exact CI signature.
- Post-fix, the full `durable-events` job sequence (events suite + the named
  schema-agreement file, both under `MAISTRO_REQUIRE_PG_LEGS=1`) passes
  end to end on that same extension-less database.
- Whole-directory run against a fresh pgvector-capable database: 157 passed,
  schema restored to `058` at session finish.
