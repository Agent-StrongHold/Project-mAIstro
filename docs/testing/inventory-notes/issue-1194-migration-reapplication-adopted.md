---
inventory-delta:
  tests/: +1
---
# issue-1194-migration-reapplication-adopted

Repairs the red `coverage (PostgreSQL)` producer at head 42945ce: the Canvas
store migration conformance suite
(`packages/maistro-canvas/tests/test_canvas_store_migration.py::TestTheChainRunsTheStore::test_reapplying_over_existing_tables_keeps_their_rows`)
upgrades to head, stamps back to 044's parent and re-upgrades — the adoption
scenario 044 documents for the chain — and revision 045 (#1194) failed that
re-application with `psycopg.errors.DuplicateColumn: column "logical_effect"
of relation "capability_invocations" already exists`, because its upgrade used
a bare `op.add_column`. A schema that already carries the column (stamped-back
repair path, or a hand-repaired live deployment) must be adopted untouched,
not fail.

## The repair

`alembic/versions/045_capability_invocation_logical_effect.py` now issues the
same guarded DDL its runtime twins already use
(`SqliteInvocationStore`/`PgInvocationStore`):
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS logical_effect BOOLEAN NOT NULL
DEFAULT FALSE` and `CREATE UNIQUE INDEX IF NOT EXISTS
uq_capability_invocation_active_logical_effect ...` — the house pattern of
revisions 025 and 044. A fresh database is built to the identical definition;
an already-migrated one is a no-op.

## The test

`tests/migrations/test_migration_chain.py::TestTheChainApplies::test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted`
drives the live chain through the exact CI walk (upgrade head, stamp
`039_quota_usage_event_identity`, upgrade head) and asserts against the
catalog: re-upgrade succeeds, `logical_effect` and the Run-scoped admission
index exist exactly once, and a row inserted before the stamp keeps its
`logical_effect = true`. Needs `MAISTRO_TEST_DATABASE_URL` and skips without
it, like the rest of the suite; `quality.yml`'s `coverage (PostgreSQL)` job
sets it, which is where the regression was caught.
