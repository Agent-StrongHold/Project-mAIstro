---
inventory-delta:
  packages/hive-conductor/backend/tests: +36
---
# claude-ws-1199-make-the-canonical-schedulestore-the-wri-41f7

Adds `test_schedule_canonical_definitions.py` (#1199), 36 node IDs: 17
scenarios parametrised over the in-memory and SQLite `ScheduleStore` (34) and
two unparametrised ones (backfill without a Container, and the runner calling
the backfill once before its first tick). They drive `/v1/schedules`
create/update/delete against a real Container and assert the canonical
definition is written first: disable, cron change, delete, template cleared,
unwired-Container 503 on create and delete, unreadable cron 422, concurrent
updates, an update queued behind a delete, a tick replaying a stale snapshot
after a disable or a delete, and the one-shot backfill.

A later round on the same PR (Codex review) adds four more scenarios,
parametrised the same way (+8 node IDs, 28 -> 36): a manual fire queued
behind a delete finds the schedule gone rather than resurrecting its
canonical row; backfill reconciles a canonical row that drifted from its
Hive row before this deploy (the old lazy tick's residual case), without
rewinding its cursor; a failed Hive write after create leaves no canonical
orphan behind; and the per-schedule lock dict releases an entry once nothing
holds or awaits it. Nothing was removed or moved.
