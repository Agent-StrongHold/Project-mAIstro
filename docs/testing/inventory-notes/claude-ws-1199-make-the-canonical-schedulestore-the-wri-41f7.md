---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
---
# claude-ws-1199-make-the-canonical-schedulestore-the-wri-41f7

Adds `test_schedule_canonical_definitions.py` (#1199), 24 node IDs: 11
scenarios parametrised over the in-memory and SQLite `ScheduleStore` (22) and
two unparametrised ones (backfill without a Container, and the runner calling
the backfill once before its first tick). They drive `/v1/schedules`
create/update/delete against a real Container and assert the canonical
definition is written first: disable, cron change, delete, template cleared,
unwired-Container 503 on create and delete, unreadable cron 422, concurrent
updates, an update racing a delete, and the one-shot backfill. Nothing was
removed or moved.
