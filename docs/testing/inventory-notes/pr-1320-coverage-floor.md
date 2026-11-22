---
inventory-delta:
  packages/maistro-core/tests: +32
  packages/hive-conductor/backend/tests: +9
---

# pr-1320-coverage-floor

Coverage-floor repair for PR #1320 (#1169 lane): the diff-coverage gate
flagged nine shipped files whose changed lines/arcs no suite reached.
This adds 41 node IDs that drive the real seams — no pragmas, no
exclusions, no floor changes.

- `tests/runs/test_execution.py` (+13): claim/launch/cancel lifecycle of
  `RunExecutionService` — cancelled-claim drain, vanished runs, racing
  terminalizers, dead-attempt reclaim, and the launch-time preconditions
  (no active run, no live attempt) that keep the lease honest.
- `tests/runs/test_service.py` (+5): `cancel_run` on runs the spine never
  saw, runs that vanished after their fence, a completion that wins the
  race with the cancel fence, fence rejection, and attempts that outlive
  their local owner.
- `tests/runtime/test_execution.py` (+1): work that finishes before its
  deadline is a success (the timeout else-arc).
- `tests/tasks/test_attempt_execution.py` (+4): queue cancellation of an
  unknown task, of a task whose canonical Run already completed (refused),
  receipt-only cancellation on a queue without an admitter, and the
  admitter reporting a Run that never existed.
- `tests/tasks/test_workspace_routing.py` (+2): WorkspaceRoutingAdmitter
  cancels a Run it admitted and reports one that never existed.
- `tests/graph/durable_runs/test_canonical_execution_store.py` (+7):
  run/node-run transitions delegate to the canonical store and mirror
  back, are idempotent on the status the store already holds, and raise
  RunIntegrityError for ghosts the spine never saw, orphans the spine
  never recorded, and a record that loses its NodeRun under the write.
- `backend/tests/test_dag_run_cancel_route.py` (+1): cancel route answers
  404 when the projection points at a canonical Run the spine never had.
- `backend/tests/test_dag_run_scope.py` (+4): `_canonical_projection`
  degrades verbatim for identity-less rows, a spine with no store, a
  spine that never saw the Run, and a spine that is down.
- `backend/tests/test_hyperlight_executor.py` (+4): subprocess and
  cmd-adapter success with env passthrough, deadline timeout kills the
  child and reports `{"error": "timeout"}`, and transport failure is
  reported, not raised.
