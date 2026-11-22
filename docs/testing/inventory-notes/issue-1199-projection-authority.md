---
inventory-delta:
  packages/hive-conductor/backend/tests: +30
---

# issue-1199-projection-authority

Added `packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py`
for the #2467 repair under #1199 (canonical schedule write authority across
restart): ten test functions parametrized over the memory, SQLite, and
PostgreSQL backends (30 collected items). The PostgreSQL legs run against a
real server migrated through the alembic chain, and the restart scenarios
close and reopen the database, so the durable tombstone and the surviving
canonical definition are read back from the store, not from the test's head.

What the tests prove:

- a canonical edit acknowledged before a crash keeps its values on restart,
  while the stale Hive projection is repaired from canonical — and the
  retired any-drift startup `put` is replayed in-test to show it would have
  reverted the same edit (the negative-before leg);
- a canonically deleted schedule is not resurrected from the Hive row a
  crash left behind: the durable deletion marker retires the row, across a
  real database reopen on SQL backends;
- a genuinely never-imported legacy row still migrates exactly once with
  real Workspace scope, and an already-imported or tombstoned row can never
  override canonical authority;
- create-crash orphans are surfaced back into the projection by startup, so
  no enabled schedule is invisible to the routes that own it;
- the by-id routes (GET/PUT/DELETE) obey canonical definition truth at read
  time, and an update whose projection write fails after the canonical
  commit answers with an explicit degraded 503 naming the persisted edit;
- recorded cursors (`runs_so_far`, `last_run_id`, `next_due_at`) survive
  projection repair untouched, and cursor-only differences are not mistaken
  for definition drift;
- repeated and concurrent startup passes are idempotent and preserve exactly
  one schedule identity.

Supporting edits move no other counts: the drifted-row scenario in
`test_schedule_canonical_definitions.py` was rewritten to the one-way
authority direction (its old assertion encoded the retired policy), the
`configured` fixture there now isolates the seeded Hive rows, and
`packages/maistro-core/tests/conftest.py` truncates the new
`schedule_deletions` table between PostgreSQL tests.

## Executed evidence (2026-11-22, head 822579df2c4a)

The closure gate's real-PostgreSQL execution, run in the lane worktree
against a pg18 server created from `pgvector/pgvector:pg18`, migrated with
`uv run alembic upgrade head` (chain applied through 069
`schedule_deletions`):

- `MAISTRO_TEST_PG_DSN=... uv run pytest
  packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -q`
  → **62 passed, 0 skipped** — every PostgreSQL leg ran, including the
  negative-before (`test_the_retired_any_drift_push_reverts_an_acknowledged_edit`)
  and positive-after (`test_restart_retains_a_canonical_edit_and_repairs_the_stale_row`)
  restart legs across a real close-and-reopen of the database.
- `MAISTRO_TEST_PG_DSN=... uv run pytest packages/maistro-core/tests -k schedul -q`
  → **368 passed** (store conformance incl.
  `test_concurrent_record_fire_on_one_store_does_not_lose_an_increment`
  on memory/SQLite/PostgreSQL, and
  `test_a_due_cursor_write_counts_no_fire_by_default`).
- `DATABASE_URL=... MAISTRO_TEST_DATABASE_URL=... uv run pytest
  tests/migrations/test_migration_chain.py
  tests/migrations/test_goal_installed_base_upgrade.py
  tests/migrations/test_capability_invocation_effect_index_migration.py -q`
  → **28 passed** (chain applies to an empty database and reverses,
  covering 069).
- Without `MAISTRO_TEST_PG_DSN`, the same suites report the PostgreSQL legs
  as explicit skips (`MAISTRO_TEST_PG_DSN is unset`) — 72 passed 26 skipped
  (canonical-due/projection/definitions), 20 passed 10 skipped
  (projection authority) — so a driver that cannot see a server is never
  mistaken for one that ran it.
- Gates: `uv run ruff check .` (clean), `uv run ruff format --check .`
  (3621 files formatted), canonical `uv run mypy packages/maistro-{core,
  server,turing,canvas,bootstrap,registry,ext-sdk}/src` (no issues in 959
  files), `scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (exit 0, 1221 reviewed
  identities = 1221 findings), `scripts/check-suite-inventory.py` (21
  suites match), `scripts/check-durable-table-inventory.py` (125 tables,
  `schedule_deletions` declared), `scripts/check-doc-links.py`,
  `scripts/check-backlog-consistency.py`, `scripts/verify-monorepo-layout.sh`
  (all ok).
