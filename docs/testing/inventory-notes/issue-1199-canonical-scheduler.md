---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/hive-conductor/backend/tests: +4
---
# issue-1199-canonical-scheduler

Added focused coverage for the M1 scheduler convergence:

- future cursor initialization is persisted and removes a schedule from the due set;
- overlapping SQLite cursor writes retain every increment and the final cursor fields;
- the live Hive tick consults canonical `ScheduleStore.due()` rather than a stale
  legacy projection;
- buffered occurrences keep the canonical due cursor visible, and two SQLite
  connections serialize cursor updates without losing fields;
- a restart resumes from the durable SQLite cursor (the stale legacy row cannot
  make the tick refire), and the next owed occurrence fires after it comes due;
- a manual `fire_now` and a live tick interleave on one durable SQLite cursor:
  each firing counts exactly once and a later tick refires neither.
