---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# 837 — registered-DAG recovery and timed wakeup

Nine new tests in `packages/hive-conductor/backend/tests/test_registered_dag_recovery.py`,
nothing removed or moved. They drive the real `run_registered_dag` admission and the
canonical in-memory stores through the new `services/registered_dag_recovery.py` halves:
a multi-node Run admitted by the production `fire_now` -> `ScheduleRunAdmitter` path (no executor marker) completes, a schedule Run lost before checkpoint 1 completes, an elapsed timer wait wakes (multi-node and single-node) while a
human pause does not, an answered HITL pause resumes, other owners' Runs (legacy DAG,
Evolve, single-node, a foreign executor, and one carrying `schedule_inputs` the durable launch snapshot cannot replay) are never touched, a foreign QUEUED prefix longer
than one tick's bound is crossed across ticks, both halves are no-ops without a graph
store, and the `dag_recovery` cadence survives one half raising.
