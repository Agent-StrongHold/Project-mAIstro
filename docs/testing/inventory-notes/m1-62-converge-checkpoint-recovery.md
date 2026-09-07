---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/hive-conductor/backend/tests: +3
---

# m1-62-converge-checkpoint-recovery

M1-E2 convergence tail (#62), building on #913/#895. The timed half of the
durable Graph recovery contract had no production consumer: `resume_due_graph_runs`
was test-only while the shipped Hive cadence recovered QUEUED bootstrap
admissions alone, so a WAITING continuation with an elapsed `resume_at` stayed
parked forever.

- `packages/maistro-core/tests/graph/durable_runs/test_recovery_wakeup.py` (+5):
  per-Run resolver factory seam, admission-source ownership guard, the
  exactly-one-resolver contract, and Event-sink threading for both the wakeup
  and bootstrap ticks.
- `packages/maistro-core/tests/graph/durable_runs/test_attempt_executor.py` (+2):
  resume reports crash dispositions on the recovery Event sink
  (`recovered_and_parked` for an orphaned RUNNING Attempt), and resume without
  a sink behaves exactly as before.
- `packages/maistro-core/tests/graph/durable_runs/test_canonical_durable_store.py`
  (+1): orphan-continuation purge leaves warning evidence (id, status, version)
  instead of deleting silently.
- `packages/hive-conductor/backend/tests/test_dag_recovery.py` (+3):
  `wake_due_dag_runs` ownership/wiring (store, resolver factory, container
  Event bus), its standalone no-op behavior, and the recovery cadence running
  both halves with an isolated bootstrap failure.

No suite shrank; no counts moved anywhere else.
