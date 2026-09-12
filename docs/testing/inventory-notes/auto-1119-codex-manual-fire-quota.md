---
inventory-delta:
  packages/maistro-core/tests: +21
---
# #1119 review: manual fire claims its quota first and leaves the cursor alone

Three behavioral cases in `scheduling/test_admission.py` and six store
conformance cases (`scheduling/test_store.py`, each over memory / SQLite /
PostgreSQL = 18 node IDs):

- a manual fire at 12:00:30 leaves `last_fired_at`/`next_due_at` where the
  cron left them, and the following tick still admits the owed 12:00
  occurrence;
- two concurrent manual fires on the last run produce exactly one Run and one
  `ManualFireRefused`;
- a store outage after the Run exists leaves the slot counted, so the next
  request is refused rather than duplicating the work;
- `reserve_fire` counts and disables on exhaustion without moving the cursor,
  refuses an exhausted schedule, never exceeds `max_runs` under concurrent
  callers, and answers None for an unknown schedule; `settle_fire` records
  the Run on confirmation and is a trace-free undo on release.
