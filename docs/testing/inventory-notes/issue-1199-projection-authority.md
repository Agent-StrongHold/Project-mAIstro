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
