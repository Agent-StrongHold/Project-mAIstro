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
  (`test_hive_row_cannot_force_a_schedule_that_is_not_due`).
