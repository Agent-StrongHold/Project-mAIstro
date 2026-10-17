---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/hive-conductor/backend/tests: +3
---
# issue-1199-canonical-scheduler

Added focused coverage for the M1 scheduler convergence:

- future cursor initialization is persisted and removes a schedule from the due set;
- overlapping SQLite cursor writes retain every increment and the final cursor fields;
- the live Hive tick consults canonical `ScheduleStore.due()` rather than a stale
  legacy projection;
- a process restart rebuilds from durable canonical state alone: two independent
  object graphs over one SQLite file, the first connection closed between them and
  the legacy `stores.schedules` dict never consulted, prove no occurrence re-fires
  after the boundary and the next one fires exactly once from the durable cursor.
