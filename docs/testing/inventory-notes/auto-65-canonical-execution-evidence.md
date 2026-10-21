---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Issue #65 repair — canonical physical execution evidence

Adds `test_goal_run_detail_exposes_canonical_node_runs_and_attempts` to the
Goal-inspection suite. It creates a real canonical Run, NodeRun, and Attempt
behind the scoped `ScopedRunReader`, then proves the same run id selected from
the Goal history returns those canonical physical records from the DAG-run
inspection seam. The projection has no local NodeRun/Attempt state.
