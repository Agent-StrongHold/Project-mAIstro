---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

The configured scheduler tick now selects due work from `ScheduleStore.due()` and admits one canonical Run per occurrence. Six Hive scheduler tests cover that seam: one due schedule, a Hive row that must not override a future cursor, a bad Hive projection that must not block admission, one admission failure that must not block the next schedule, a SQLite restart that executes the queued Run once, and a cursor crash that reconciles to the same Run.
