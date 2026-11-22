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

## Executed evidence (2026-11-22, head e5459fbfd55e, independent re-validation)

A fresh verification round re-executed the closure gate first-party against a
newly created pg18 server (`pgvector/pgvector:pg18` on 127.0.0.1:18998) — not
the previous round's container — migrated with `uv run alembic upgrade head`
(DATABASE_URL + MAISTRO_TEST_PG_DSN, chain applied through 069
`schedule_deletions`, `alembic current` = 069 head):

- projection authority + canonical due on real PG: **62 passed, 0 skipped**
  (standalone: projection authority 30 passed; canonical due 32 passed) —
  including the negative-before leg
  (`test_the_retired_any_drift_push_reverts_an_acknowledged_edit`), the
  positive-after restart legs across a real close-and-reopen of the database,
  deletion non-resurrection, one-time tombstone-aware legacy migration, and
  the degraded-503 semantics.
- `packages/maistro-core/tests -k schedul`: **368 passed** with PG legs live;
  `test_concurrent_record_fire_on_one_store_does_not_lose_an_increment`
  re-run standalone across the memory/SQLite/PostgreSQL parametrizations:
  **3 passed**. (Procedural note: this test errored once in the round when a
  concurrently running migration-chain suite truncated shared scratch tables
  on the same database — a harness-parallelism artifact, not a product
  failure; the sequential re-run passes.)
- Named admission/restart AC tests: `test_restart_executes_the_queued_run_once`,
  `test_restart_after_a_cursor_crash_keeps_the_same_run`,
  `test_two_live_runners_claim_one_occurrence`,
  `test_hive_row_cannot_force_a_schedule_that_is_not_due` — **4 passed**;
  due-cursor tests (`test_admission.py -k cursor`) **22 passed**.
- Broader scheduler surface (scheduler, bounded tick, canonical
  admission/definitions, manual fire, frequency floor, scope, workspace scope,
  timezone health incl. the real `start_scheduler()` loop task): **176
  passed**.
- Migration chain on the fresh server: `tests/migrations/
  {test_migration_chain,test_goal_installed_base_upgrade,
  test_capability_invocation_effect_index_migration}.py` — **28 passed**
  (apply + reverse, covering 069). Run sequentially with the other
  database-backed suites; they share the scratch database.
- Skip semantics re-proven: without `MAISTRO_TEST_PG_DSN`, projection
  authority reports **20 passed, 10 skipped** (explicit skips), so an
  environment without a server is never mistaken for one that ran it.
- Gates, this head: `uv run ruff check .` clean; `uv run ruff format --check .`
  (3621 files formatted); `scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1221 = 1221);
  `scripts/check-suite-inventory.py` via `uv run python3` — **21 suites match,
  exit 0** (a bare-`python3` invocation without the uv venv reports collection
  errors; use `uv run`); `scripts/check-durable-table-inventory.py` ok (125
  tables); `scripts/check-test-duplicates.py` ok (0 groups).

Suite counts are unchanged by this note; no new `inventory-delta` is recorded.

## Executed evidence (2026-11-22, head 45ef9fd2d5d96ac067ba52e77240798cef3c04ca)

Revalidated the assigned head directly, after the previous verifier's
`pytest .../conftest.py` invocation exited 5 because that file collects no
tests. A fresh pgvector/pg18 server was migrated through Alembic head 069:

- Real-PG projection authority, canonical due, and projection suites with
  `MAISTRO_REQUIRE_PG_LEGS=1`: **118 passed, 1 skipped** (the memory-only
  independent-process case is intentionally inapplicable).
- Core scheduling tests with PG legs required: **327 passed**.
- Strict #459 closeout selection (`schedule_required or schedule_fire or
  scaffold_only`): **3 passed**, emitting
  `M1_PARITY_EVIDENCE {"executed": true, "status": "PASSED",
  "scenario": "scheduler-occurrence-to-conductor"}`.
- Additional due/admission/store and scheduler projection tests: **300 passed,
  81 skipped** across explicitly optional-backend runs; the PG-required suites
  above cover the durable backend legs.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (3630
  files formatted).

The failed no-tests-collected command was a validation-target error, not a
product failure; rerunning the actual test modules and the strict closeout
selection resolved it. No test inventory delta is introduced by this evidence
update.
