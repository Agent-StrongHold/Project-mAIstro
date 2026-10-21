---
inventory-delta:
  packages/maistro-core/tests: +11
---
# #1151: committed Graph success with a lost acknowledgement

Added one real-PostgreSQL regression in `tests/runs/test_pg_spine_crash_windows.py`
and ten narrow refusal/result tests in
`tests/graph/durable_runs/test_frontier_active_attempt_guard.py`.

The PostgreSQL case injects an ordinary `OSError` after the canonical COMPLETED
write commits but before its caller receives acknowledgement. An independent
pool verifies the committed payload before injection. Before the repair, the
Graph reports FAILED / PhysicalExecutionError despite persisted success.
The expected path folds that exact launched Attempt's persisted result without
another provider execution, completion write, Attempt, or traversal step
(`max_steps=1`). Independent reads assert canonical/continuation completion,
accepted Attempt identity, retained history and no-op repeated recovery.

The narrow tests cover absent and every non-COMPLETED Attempt, missing launched
identity, classified infrastructure failure, and a physically COMPLETED result
whose logical failure must still reach node policy. They assert exact-ID reads,
no adoption of older Attempts and no retry of the terminal write. The existing
pre-commit write-loss PostgreSQL test remains the contrasting uncommitted-output
case: live ownership is retained and eventual reclaim parks, never fabricating
success.

No general parked disposition, retry policy, scan policy, provenance writer or
new recovery authority is introduced. Parent acceptance remains blocked by its
separate parked-state and total-inspection-work obligations. This fault injection
models acknowledgement loss at the store API boundary, not a dropped network
COMMIT response or OS process kill.
