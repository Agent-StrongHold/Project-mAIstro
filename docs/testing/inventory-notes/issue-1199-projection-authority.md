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

## Exact assigned-head validation (398ddb87a613)

Re-executed against the assigned candidate head in this repair round:

- With a fresh-on-suite PostgreSQL scratch database from the running pg18
  service and `MAISTRO_REQUIRE_PG_LEGS=1`, projection authority, canonical due,
  and projection suites: **118 passed, 1 skipped** (the in-memory
  independent-process case is intentionally inapplicable).
- `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest packages/maistro-core/tests
  -k schedul -x -q` against that pg18 service: **368 passed**, including
  SQLite/PostgreSQL cursor-write serialization and due-cursor persistence.
- Scheduler-focused Hive suite: **264 passed, 46 skipped**; optional database
  cases were skipped because this invocation did not set a database DSN.
- Strict configured scheduler-to-Conductor closeout selector: **3 passed**,
  emitting `M1_PARITY_EVIDENCE` with `executed=true` and `status=PASSED`.
- `uv run ruff check .` and `uv run ruff format --check .`: passed (3630
  files formatted).

The PostgreSQL service was explicitly migrated through Alembic head 069 before
running the store conformance suite. A first combined PG invocation exposed
that `test_schedule_projection_authority.py` expects its configured database
to already be migrated (`relation "schedules" does not exist`); after applying
`uv run alembic upgrade head`, the complete three-module run above passed. This
was test-environment setup, not a code change. No tests were added and the
existing inventory delta is unchanged.

## Repair-round exact-head validation (06dd4ef1c551)

The dispatch verifier's `pytest packages/maistro-core/tests/conftest.py -q -x`
returned exit 5 because a conftest is not a test module (no tests collected).
Replaced that invalid target with executable behavior suites at this exact
candidate head:

- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -q -x`
  → **39 passed, 29 skipped** without PostgreSQL configured.
- Repeated those suites with required PostgreSQL legs on the lane's live
  PostgreSQL 18 service → **67 passed, 1 skipped**; the skip is the
  intentionally inapplicable memory-only independent-process scenario. The
  projection fixture creates a scratch DB and upgrades it through Alembic head.
- `uv run pytest packages/maistro-core/tests -k schedul -x -q` → **321 passed,
  47 skipped** without PostgreSQL; repeating with required PostgreSQL legs
  → **368 passed, 0 skipped**, including store concurrency and cursor
  persistence on PostgreSQL.
- `uv run pytest packages/hive-conductor/backend/tests -k 'scheduler or schedule' -x -q`
  → **264 passed, 46 skipped**.
- Strict closeout selector,
  `uv run pytest tests/cross_product_parity/test_cross_product_parity.py -k 'schedule_required or schedule_fire or scaffold_only' -q -s`
  → **3 passed**, emitted executed/PASSED
  `scheduler-occurrence-to-conductor` evidence.
- `uv run ruff check . && uv run ruff format --check .` → clean; 3630 files
  formatted.

This repairs the failed validation target; it required no production or test
changes. No tests were added and the existing inventory delta is unchanged.

## Follow-up repair round at 85a7c708c67e (2026-11-23)

The verifier's attempt to run `packages/maistro-core/tests/conftest.py` again
returned exit 5 (`no tests ran`): a conftest is setup, not an executable test
module. Ran instead:

- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py packages/hive-conductor/backend/tests/test_scheduler_bounded_tick.py packages/hive-conductor/backend/tests/test_schedule_canonical_definitions.py packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py -q -x`
  → **98 passed, 29 skipped** in 14.59s. PostgreSQL-dependent cases were
  explicitly skipped because this command had no PostgreSQL test DSN configured.

No production or test code changed and no tests were added; the inventory
delta above remains unchanged. The skipped database legs remain unverified in
this round; prior PostgreSQL evidence is recorded above but was not re-run.

## Exact-head revalidation at 8263bd487fde (2026-11-23)

Re-ran acceptance evidence on the assigned head with the lane's PostgreSQL 18
service (`auto-1199-r3-pg`, port 18995), migrated to Alembic head 069:

- Projection authority, canonical due, and canonical admission suites with
  `MAISTRO_REQUIRE_PG_LEGS=1`: **86 passed, 1 skipped**. The skip is the
  intentionally inapplicable memory-only independent-process case; PostgreSQL
  cases ran against the real service, including restart, edit/delete recovery,
  cursor and occurrence claims.
- Core scheduling suite with required PostgreSQL legs:
  `uv run pytest packages/maistro-core/tests -k schedul -x -q` → **368 passed**.
- Strict configured scheduler-to-Conductor closeout selector → **3 passed**;
  emitted `M1_PARITY_EVIDENCE` with `executed=true` and `status=PASSED`.
- `uv run ruff check . && uv run ruff format --check .` passed (3630 files
  formatted); `scripts/check-suite-inventory.py` passed (21 suites); durable
  table inventory passed (125 tables); exact CI vulture command passed
  (1221 reviewed identities, 1221 findings).

The initial PG attempt used a SQLAlchemy `postgresql+asyncpg://` URL for a
fixture that passes `MAISTRO_TEST_PG_DSN` to psycopg and failed during fixture
setup (`missing "="`); corrected the test DSN to standard `postgresql://` and
the complete required-PG test selection passed. No tests or suite counts were
added or removed in this validation; the existing inventory delta is unchanged.

## Repair-round revalidation at 631ca81c6424 (2026-11-23)

The dispatched verifier again targeted `packages/maistro-core/tests/conftest.py`,
which is not an executable test module and exits 5 (`no tests ran`). Replaced
that invalid target with actual suites on this exact head:

- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py -q -x`
  → **39 passed, 29 skipped** in the optional-backend run.
- Repeated the same Hive suites with `MAISTRO_REQUIRE_PG_LEGS=1` against the
  lane's pg18 service (`127.0.0.1:18995`) → **67 passed, 1 skipped**; the
  sole skip is the intentionally inapplicable in-memory independent-process
  scenario. The first connection attempt used an incorrect local password and
  failed during fixture setup; corrected the DSN from the container's local
  configuration and reran the complete selection successfully.
- `uv run pytest packages/maistro-core/tests -k schedul -x -q`
  → **321 passed, 47 skipped** without a PostgreSQL DSN; repeating with
  `MAISTRO_REQUIRE_PG_LEGS=1` against that service → **368 passed, 0 skipped**.
- `uv run pytest packages/hive-conductor/backend/tests -k 'scheduler or schedule' -x -q`
  → **264 passed, 46 skipped**.
- Strict configured scheduler-to-Conductor parity selector
  (`uv run pytest tests/cross_product_parity/test_cross_product_parity.py -k
  'schedule_required or schedule_fire or scaffold_only' -q -s`) → **3 passed**;
  emitted `M1_PARITY_EVIDENCE` with `executed=true`, `status=PASSED`, and
  `scenario=scheduler-occurrence-to-conductor`.
- `uv run ruff check . && uv run ruff format --check .` → passed (3630 files
  formatted).

This resolves the invalid test target as a validation issue, not a product
regression. Real PostgreSQL acceptance legs were rerun successfully as recorded
above. No tests or suite counts were added or removed, so the existing
inventory delta is unchanged.

## Exact assigned-head revalidation at ac68b22d1bd3 (2026-11-23)

The dispatched check attempted to execute `packages/maistro-core/tests/conftest.py`
and exited 5 (`no tests ran`); this is a non-test setup file, not a product
failure. Re-ran executable acceptance suites at the exact candidate head:

- `MAISTRO_TEST_PG_DSN=... MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest
  packages/maistro-core/tests/scheduling
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py
  packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  -x -q` against the lane's running PostgreSQL 18 service → **413 passed,
  1 skipped**. PostgreSQL legs were required and ran; the single skip is the
  explicitly inapplicable memory-only independent-process scenario.
- Scheduler tests without a DSN → **58 passed, 29 skipped**; skips are
  backend-dependent integration cases, so this run is supplemental only and
  not the PostgreSQL acceptance evidence.
- Strict scheduler-to-Conductor closeout selector → **3 passed**, emitted
  `M1_PARITY_EVIDENCE` with `executed=true`, `status=PASSED`, and
  `scenario=scheduler-occurrence-to-conductor`.
- `uv run python scripts/check-suite-inventory.py` → 21 suites match;
  `uv run ruff check .` and `uv run ruff format --check .` → clean;
  exact CI vulture command → 1221 reviewed identities = 1221 findings.

No tests or suite counts were added or removed; the existing inventory delta
is unchanged.

## Assigned-head independent acceptance revalidation at 1340843a52c1 (2026-11-23)

Re-executed the live behavior at the exact assigned head rather than relying on
prior-run claims:

- `uv run pytest packages/maistro-core/tests/scheduling packages/hive-conductor/backend/tests/test_scheduler.py packages/hive-conductor/backend/tests/test_schedule_projection_authority.py packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py -x -q`
  → **413 passed, 68 skipped** (without a DSN; database legs skipped).
- Created a fresh `auto1199fresh` database on the lane's pg18 service and
  migrated it with `uv run alembic upgrade head` through 069. Required-PG
  projection authority + canonical-due suites → **67 passed, 1 skipped**;
  skip is the memory-only independent-process case.
- On that fresh migrated DB, `MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest
  packages/maistro-core/tests -k schedul -x -q` → **368 passed**, including
  SQLite/PostgreSQL `record_fire` serialization and due-cursor persistence.
- Explicit cursor regressions on fresh PG: concurrent `record_fire`,
  no-occurrence cursor write, and `TestTheDueCursorIsRecordedWithoutAFire`
  → **12 passed** across memory/SQLite/PostgreSQL parametrizations.
- Strict scheduler-to-Conductor closeout selector
  (`test_schedule_required_scenario_emits_strict_closeout_evidence`) →
  **1 passed**, exercising configured scheduler lifespan and emitting the
  scenario evidence.
- `uv run ruff check .`, `uv run ruff format --check .`, exact CI vulture
  command, and `uv run python scripts/check-suite-inventory.py` all passed
  (1221/1221 vulture identities; 21 suites match).

An initial broad scheduler run against a reused scratch database failed in an
unrelated cancellation/active-run-cap crash test; an isolated rerun on that
reused DB also failed before its subprocess checkpoint. Re-running the full
suite on a fresh migrated database passed 368/368, demonstrating scratch-DB
contamination rather than a scheduler acceptance failure. No tests or suite
counts were changed; inventory delta remains unchanged.

## Independent assigned-head acceptance revalidation at beb759beb51e (2026-11-23)

Executed on the assigned head with the live PostgreSQL 18 service at port
18995; the Postgres fixture created and migrated its own scratch database:

- `MAISTRO_TEST_PG_DSN=... MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest
  packages/maistro-core/tests/scheduling
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py
  packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  -x -q` → **413 passed, 1 skipped**. This executes the due tick against
  SQLite and real PostgreSQL, cursor updates, canonical Run/Attempt admission,
  and projection edit/delete/restart cases with PostgreSQL legs required. The
  single skip is the explicitly inapplicable memory-only process test.
- Hive scheduler, projection, and bounded-tick suites → **105 passed, 17
  skipped**; database-dependent skips were not counted as PG evidence above.
- Strict scheduler-to-Conductor parity selector → **3 passed**, emitted
  `M1_PARITY_EVIDENCE` with `executed=true`, `status=PASSED`, and
  `scenario=scheduler-occurrence-to-conductor`.
- `uv run ruff check . && uv run ruff format --check .` passed (3642 files);
  `uv run python scripts/check-suite-inventory.py` passed (21 suites match).

No tests or suite counts were added or removed; inventory delta is unchanged.

## Repair-round exact-head acceptance revalidation at 09a8dfec1b9e (2026-11-23)

The prior verifier command `uv run pytest packages/maistro-core/tests/conftest.py
-q -x` collected no tests and exited 5; this was a validation-target error,
not a product failure. Replaced it with actual scheduler test modules and ran
against the assigned head:

- `uv run pytest packages/maistro-core/tests/scheduling
  packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py
  packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -x -q`
  without a DSN → **328 passed, 67 skipped** (backend-dependent legs skipped).
- Against the live pg18 service (`auto-1199-r3-pg`, port 18995), with
  `MAISTRO_REQUIRE_PG_LEGS=1`, projection-authority and canonical-due suites
  → **67 passed, 1 skipped**; the sole skip is the memory-only independent-
  process scenario. The fixture creates its own scratch database and applies
  Alembic through head before the tests.
- On the same real PostgreSQL service, required-PG core scheduling suite
  (`packages/maistro-core/tests/scheduling`) → **327 passed, 0 skipped**.
- Strict scheduler-to-Conductor closeout selector
  (`schedule_required or schedule_fire or scaffold_only`) → **3 passed**.
- `uv run ruff check .`, `uv run ruff format --check .`, suite inventory,
  durable-table inventory, and the exact CI vulture command all passed (21
  suites match; 125 declared durable tables; 1221/1221 reviewed identities).

No tests or suite counts were added or removed; inventory delta is unchanged.

## Repair-round exact-head acceptance revalidation at 0b1a32c4a9c8 (2026-11-23)

The dispatched command `uv run pytest packages/maistro-core/tests/conftest.py
-q -x` exited 5 because a conftest is not a test module (`no tests ran`).
Executed acceptance behavior at this head instead:

- Against the lane's real PostgreSQL 18 service (`auto-1199-r3-pg`, port
  18995), with `MAISTRO_REQUIRE_PG_LEGS=1`, projection-authority, canonical-
  due, and schedule-projection-authority suites → **118 passed, 1 skipped**.
  The skip is the intentionally inapplicable memory-only independent-process
  scenario; PostgreSQL fixtures create and migrate scratch databases.
- Required-PG core scheduling selection (`uv run pytest
  packages/maistro-core/tests -k schedul -x -q`) → **368 passed**, including
  due-cursor persistence and serialized SQLite/PostgreSQL `record_fire`.
- The strict scheduler-to-Conductor closeout test
  (`test_schedule_required_scenario_emits_strict_closeout_evidence`) → **1
  passed**, emitting `M1_PARITY_EVIDENCE` with `executed=true`,
  `status=PASSED`, and `scenario=scheduler-occurrence-to-conductor`.
- `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run python scripts/check-suite-inventory.py`,
  `uv run python scripts/check-test-duplicates.py`, and the exact CI vulture
  command all passed: 21 suites match, no duplicate test files, and 1221/1221
  reviewed identities.

No tests or suite counts were added or removed; inventory delta is unchanged.

## Writer exact-head revalidation at 6de36e84bf8a (2026-11-23)

The dispatched verifier's `pytest packages/maistro-core/tests/conftest.py` exited 5 (`no tests ran`); a conftest is fixture setup, not an executable test module. Re-ran acceptance suites on the assigned committed tree:

- `uv run pytest packages/maistro-core/tests/scheduling packages/hive-conductor/backend/tests/test_scheduler_projection_authority.py packages/hive-conductor/backend/tests/test_scheduler_canonical_due.py -q -x` → **328 passed, 67 skipped** without PostgreSQL.
- With `MAISTRO_REQUIRE_PG_LEGS=1` and the running lane-owned pg18 service (`auto-1199-r3-pg`, port 18995), the same three suites → **394 passed, 1 skipped**; the sole skip is the inapplicable memory-only independent-process scenario. PostgreSQL fixtures create isolated scratch databases and migrate them through Alembic head.
- The projection-authority, canonical-due, and schedule-projection-authority suites with mandatory PostgreSQL legs → **118 passed, 1 skipped**.
- Strict #459 scheduler-to-Conductor selector (`schedule_required or schedule_fire or scaffold_only`) with mandatory PostgreSQL configuration → **3 passed**.
- `uv run ruff check .` and `uv run ruff format --check .` passed (3644 files).

These runs exercise canonical due ticking, cursor persistence/concurrency, canonical Run/Attempt behavior, persisted projection reconciliation and restart cases. No tests or suite counts were added or removed; inventory delta is unchanged.
