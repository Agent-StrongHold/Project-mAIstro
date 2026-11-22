# issue-1199-canonical-scheduler

This branch first carried a parallel implementation of #1199 (tick from
canonical `ScheduleStore.due()`, persist every computed `next_due_at`,
serialized SQLite `record_fire`) with its own focused tests. Before this sync,
`origin/develop` landed the same convergence through reviewed PRs — #1304
(record the due cursor on every evaluation; serialize SQLite `record_fire`),
#1603 (canonical `ScheduleStore` as the write authority for `/v1/schedules`
definitions), #1625/#1666 (per-occurrence canonical Run admission and claims) —
with strictly broader coverage: the concurrency test runs against every store
implementation, the tick/restart tests drive a real wired Container, and the
due-cursor tests cover the future-not-due defect at admission level.

The develop sync therefore resolves every conflict in favor of the develop
implementation and retires this branch's superseded parallel code and tests.
No suite count moves relative to the synced base, so no `inventory-delta` is
recorded. Acceptance coverage on the merged tree:

- the live tick enumerates candidates from `ScheduleStore.due()`
  (`services/scheduler.py` `_tick_due`; the legacy `stores.schedules` dict is a
  response projection and an unwired-fallback only);
- every evaluation persists the computed `next_due_at`, including evaluations
  that fire nothing (`test_admission.py::TestTheDueCursorIsRecordedWithoutAFire`);
- overlapping SQLite `record_fire` callers cannot lose cursor updates
  (`test_store.py::test_concurrent_record_fire_on_one_store_does_not_lose_an_increment`,
  parametrized over all store implementations);
- a restart resumes from durable canonical state without re-firing
  (`test_scheduler_canonical_admission.py::test_restart_executes_the_queued_run_once`,
  `test_restart_after_a_cursor_crash_keeps_the_same_run`);
- a stale Hive row cannot force a schedule that is not due
  (`test_hive_row_cannot_force_a_schedule_that_is_not_due`);
- occurrence uniqueness stays owned by the Run store's `(schedule_id,
  scheduled_for)` claim (#850/#220), not the tick: two concurrent tick
  evaluations of one schedule produce one Run and one counted fire
  (`test_scheduler_canonical_admission.py::test_two_live_runners_claim_one_occurrence`);
- the real tick runs on both supported SQL backends
  (`test_scheduler_canonical_due.py`, parametrized over `SqliteScheduleStore`
  and `PgScheduleStore` on the real alembic schema).

First-party re-validation at the pre-sync head cd4fdd4d7 (pgvector:pg18
container, real alembic chain to head): the core scheduling suite passes with
the PostgreSQL legs live (311 passed, 0 skipped),
`test_scheduler_canonical_due.py` passes 28/28 against PostgreSQL, and
`test_concurrent_record_fire_on_one_store_does_not_lose_an_increment` passes
across the memory, SQLite, and PostgreSQL parametrizations. At that head the
repo-wide suite-inventory gate reported `DRIFT tests/: expected 5260,
collected 5261`; collecting `tests/` at the then-synced base commit (2f56be40)
in the same environment also yielded 5261, so the one-test drift was inherited
from that base, not introduced by this branch (whose diff is this note and the
ADR status update only).

CI at cd4fdd4d7's successor e552fca6c reded on exactly that drift (the `test`
job's inventory step) and on the coverage gate's base-inherited publish-set
floor. The sync merge to origin/develop (1a2e12656) resolves both: develop
reconciled the inventory, and the merged head collects `tests/: 5504` with the
gate reporting `ok: 17 suite(s) match the recorded inventory`. The diff leg of
the coverage gate passes on this head by construction — `git diff
1a2e12656...HEAD` is this note and the ADR status update, zero measured Python
files — and the 87% publish-set floor is content-determined by the merged
develop base, which this branch's docs-only diff cannot move.

Merged-head (cbcaa5c28) re-validation, all commands run first-party:

- core scheduling with the PG legs live (pgvector:pg18, `alembic upgrade head`
  to 063): `packages/maistro-core/tests/scheduling/` 311 passed, 0 skipped;
- `test_scheduler_canonical_due.py` 28/28 (14 sqlite + 14 postgres legs on the
  real alembic schema); the canonical admission/due/manual-fire/definition
  suites together 92 passed;
- `test_concurrent_record_fire_on_one_store_does_not_lose_an_increment` across
  the memory, SQLite, and PostgreSQL parametrizations;
- the `test` job's Python steps at this tree, CI environment (REQUIRE_AUTH=
  false, MAISTRO_DRY_RUN=1, no services): root `tests/` 5276 passed / 135
  skipped; hive-conductor backend 3654 passed / 20 skipped; server, turing
  (both suites), design, ext-harness, ext-sdk 1857 passed / 9 skipped; the
  one-process cross-suite leakage proof 9595 passed / 156 skipped;
- gates: `check-suite-inventory.py` ok, `check-test-duplicates.py` ok,
  `check-diff-coverage.py --base 1a2e12656` ok (0 changed files measured),
  ruff check and format clean.

CI repair at the merged head (49e60c36), first-party: the merge-queue
coverage (no services) job red on
`test_cross_process_peer_injection_refused_by_canonical_warden` — the
`_PEER_SERVER` child made the port file visible before the port bytes were
flushed and a parent poll read `''` (`int('')` ValueError), taking
down `coverage-gate` and `gates-ran` with it. See
[issue-1199-coverage-port-file-race.md](issue-1199-coverage-port-file-race.md)
for the CI-log-derived root cause, the atomic-publish + tolerant-poll fix, and
the regression proof (new test reproduces the exact CI error against the
unfixed helper, then passes; a2a directory 281 passed).

## Re-validation at the #46-reactivation head 4dd5c94af8 (2026-11-22)

First-party re-run of the acceptance-relevant suites at this exact head
(`auto-46` = 4dd5c94af835b86e71325da7ffac0a261f7d0623, base 33ac30c5):

- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `uv run mypy` over the seven documented package srcs: no issues in 905 files.
- `scripts/check-suite-inventory.py`: ok, 21 suites match;
  `scripts/check-test-duplicates.py`: ok, no byte-identical test files.
- Core scheduling with the PostgreSQL legs live (dedicated pgvector:pg18
  container on the real `alembic upgrade head` chain, 063 at this head):
  `packages/maistro-core/tests/scheduling/` 311 passed, 0 skipped
  (`MAISTRO_TEST_PG_DSN`); without the DSN the same suite is 274 passed,
  37 skipped — every skip is a PostgreSQL leg, and every one goes green live.
- Hive-conductor scheduler/definition/scope suites
  (`test_scheduler*.py`, `test_schedule_*.py`, `test_manual_fire_canonical.py`,
  `test_schedule_manual_fire_canonical.py`): 181 passed / 14 skipped without
  PG; 195 passed / 0 skipped with the same live DSN.

Reactivated-#46 status at this head: the #2467 projection-authority defect is
still present — `services/scheduler.py::run` calls
`backfill_canonical_definitions()` unconditionally on every startup (line 363)
and `_backfill_one` puts a Hive-row-derived definition whenever the canonical
row is missing or drifted (lines 332–344), while `routes/schedules.py`
commits canonical writes before the Hive projection (update: lines 402→406;
delete: lines 425–426). A crash between those writes is therefore "repaired"
at next startup by the stale projection overwriting or resurrecting canonical
state. The one-time/tombstone-aware migration and projection-repair work for
that defect is owned by the reopened #1199 and #2467 lanes (heads
1326ca7eb4 / c486fc806f, not ancestors of this branch); no test count moves
here, so no `inventory-delta` is recorded for this addendum.
