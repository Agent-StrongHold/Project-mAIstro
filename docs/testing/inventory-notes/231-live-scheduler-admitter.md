---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---

# #231 live scheduler admission

Adds five end-to-end tests at the shipped Hive scheduler boundary. They prove
that two scheduler runners cannot create two Runs for one occurrence, a
persisted GraphTemplate survives an empty process-local DAG registry after
restart, an unresolved template leaves the occurrence owed, Run creation
failure also leaves the occurrence owed, and `max_runs` disables both canonical
schedule state and the legacy Hive projection.
