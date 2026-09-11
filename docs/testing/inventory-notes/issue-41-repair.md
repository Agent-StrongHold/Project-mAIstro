---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  tests/: +1
---
# Issue 41 repair

Added one Hive Conductor regression test proving the demo LocalTaskBackend
passes the canonical task-admission claim store into TaskQueue, and one live
PostgreSQL migration-chain test proving migration 034 refuses a table whose
column names match but whose type/default does not.
