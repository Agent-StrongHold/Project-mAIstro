---
inventory-delta:
  packages/hive-conductor/backend/tests: +34
  packages/maistro-core/tests: +3
---

Six canonical admission tests cover due-only selection, isolation from malformed Hive projections and admission failures, and queued/cursor-crash recovery. Twenty-eight durable real-tick cases run fourteen scenarios on SQLite and PostgreSQL: canonical-only execution, no-fire next-due persistence, consuming queued Runs after a due read failure, canonical audit identity, stale selection versus deletion/disable/recurrence/cursor edits, manual/tick locking, no per-tick legacy backfill, restart before/after cursor recording, and pending manual-marker recovery before/after Run creation despite a future recurrence cursor. Three core backend cases prove the same pending-selection predicate preserves disabled-row behavior and does not itself mutate a reservation. The PostgreSQL CI step requires its backend legs; local runs without a test server explicitly skip them.
