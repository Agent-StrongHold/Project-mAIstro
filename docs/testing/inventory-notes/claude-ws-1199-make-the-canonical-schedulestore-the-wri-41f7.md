---
inventory-delta:
  packages/hive-conductor/backend/tests: +22
---
# claude-ws-1199-make-the-canonical-schedulestore-the-wri-41f7

Adds `test_schedule_canonical_definitions.py` (#1199): 11 scenarios, each
parametrised over the in-memory and SQLite `ScheduleStore`, for 22 node IDs.
They drive `/v1/schedules` create/update/delete against a real Container and
assert the canonical definition is written first (disable, cron change,
delete, template cleared, unwired-Container 503, unreadable cron 422, update
racing a delete) plus the one-shot backfill and the runner calling it once
before its first tick. Nothing was removed or moved.
