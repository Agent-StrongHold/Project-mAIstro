---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/hive-conductor/backend/tests: +2
---
# issue-1199-canonical-scheduler

Added focused coverage for the M1 scheduler convergence:

- future cursor initialization is persisted and removes a schedule from the due set;
- overlapping SQLite cursor writes retain every increment and the final cursor fields;
- the live Hive tick consults canonical `ScheduleStore.due()` rather than a stale
  legacy projection;
- buffered occurrences keep the canonical due cursor visible, and two SQLite
  connections serialize cursor updates without losing fields.
