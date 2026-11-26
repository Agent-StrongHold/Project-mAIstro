---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# 1199-develop-sync-33ac30c5-renumber-069

Develop-sync resolution for the #1199 lane. The worktree held an in-progress
merge of `33ac30c5f1` (a `origin/develop` ancestor; the round then merged
`origin/develop` `b52086730c` on top, so the branch now contains develop
fully). No test was added or removed — the resolution renumbered this lane's
unlanded migration and re-validated; `scripts/check-suite-inventory.py`
reports all 21 suites matching the recorded inventory at the merged head.

## The collision and the resolution

Develop landed `064_canonical_personas` … `068_legacy_principal_ownership`
while this branch carried the unlanded `064_schedule_deletions` (#2467
tombstone table). A landed trunk migration never moves, so the schedule
deletion-marker revision renumbers onto develop's tip:

- `alembic/versions/069_schedule_deletions.py` — `revision = "069"`,
  `down_revision = "068"`; the alembic graph is one linear head again
  (`heads == ['069']`, `063 ← 062 … 069 ← 068`);
- `tests/migrations/test_capability_invocation_effect_index_migration.py` and
  `tests/migrations/test_goal_installed_base_upgrade.py` — head pins move to
  `069`/`CHAIN_HEAD`, keeping both sides' landed-identity asserts verbatim;
- `tests/migrations/test_migration_chain.py` — `EXPECTED_TABLES` gains
  `schedule_deletions` (the exact live-catalog equality refuses a chain-owned
  table the ledger omits);
- `KNOWN-GAPS.md` tombstone reference moves to alembic `069`.

## The guarded-DDL repair the PG leg caught

`tests/migrations/test_migration_chain.py::TestTheChainApplies::
test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted` failed
against real PostgreSQL before the fix: the schedule-deletion revision used an
unguarded `op.create_table`, so the stamp-back + re-upgrade repair walk died
with `DuplicateTable: relation "schedule_deletions" already exists` — the
exact failure class the chain's adoption contract exists to catch (#1194's
045). `upgrade()` now uses guarded `CREATE TABLE IF NOT EXISTS` /
`DROP TABLE IF EXISTS` like 063/064, preserving the original shape
(`schedule_id TEXT PK`, `deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`),
which is what `PgScheduleStore.delete` writes (`VALUES ($1, NOW())`).
Negative-before/positive-after evidence: the adoption test failed at the
merge head with the unguarded DDL and passes after; both runs are on this
round's real server.

## Validation evidence (real PostgreSQL, pgvector:pg18)

`MAISTRO_TEST_DATABASE_URL`/`MAISTRO_TEST_PG_DSN` against a lane-dedicated
scratch database (`auto1199_scratch`), never another lane's `maistro`
database:

- `uv run python -m alembic upgrade head` from empty: runs `… 068 -> 069,
  Durable Schedule deletion markers (#2467)`, stamps `069`;
- `tests/migrations/test_migration_chain.py`: 18 passed (was 1 failed);
- `tests/migrations/test_goal_installed_base_upgrade.py` +
  `test_capability_invocation_effect_index_migration.py`: 10 passed;
- `packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py`
  with PG legs live: 30 passed (was 20 passed / 10 skipped);
- `packages/maistro-core/tests/scheduling` +
  `test_schedule_canonical_definitions.py` with PG legs live: 363 passed
  (was 289 passed / 38 skipped);
- runs suites carried by the sync (#2425/#2427): 95 passed;
- `uv run ruff check .` and `ruff format --check .`: clean;
- mypy (CI argv): no issues in 959 files;
- `check-suite-inventory`, `check-test-duplicates`,
  `check-durable-table-inventory` (125 tables), `check-merge-markers`: ok;
- `quality/*.json` row-survival audit across the merge: no rows lost from
  either side (29 files compared by multiset against both parents).
