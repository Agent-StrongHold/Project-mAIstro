---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# Issue #35: DAG-run projection cannot own terminal truth

Twelve contract tests in
`packages/hive-conductor/backend/tests/test_dag_run_projection_authority.py`
pin the "DagRunStore class of defect" closure from issue #35's census: a
surviving product projection may not independently terminalize or resurrect
work that the canonical Run/NodeRun/Attempt spine disagrees with.

Read side (`services/dag_run_inspection`): planted contradictory rows —
failed-against-completed, completed-against-failed, and terminal-against-
still-running — all serve the canonical status through list and detail;
uncorrelated rows and rows whose canonical Run no longer resolves are served
as recorded (the documented receipt boundary); reconciliation never rewrites
the stored record or the durable row behind it; a replica that rehydrates a
contradictory durable row via `reload()` still serves canonical truth; and
serving a contradiction leaves the canonical record untouched.

Write side (`services.chat_completion._tool_run_workflow`): the chat
workflow tool's success and canonical-failure paths copy the canonical
outcome and `canonical_run_id` into the projection row instead of stamping a
locally decided terminal status, and the failure-written row is reconciled
by the same read path as every other row. The generic-exception branch is
pinned from both sides: a facade crash before any canonical verdict still
closes the row (#697) with the writer's witnessed attempt-local display
fact and no invented correlation, and a crash after admission leaves the
correlated row's locally stamped display `failed` outranked by the spine
(the read overlay serves a still-running canonical Run over it). A
bookkeeping crash after the facade returned records the canonical outcome
it is holding -- status and canonical identity, under the same #1036
contract as the success path -- not a bare locally re-decided status.

Boundary: a source-level fitness assertion pins that the execution-side
modules (scheduler, dag_recovery, canonical_dag_runner, dag_agents) never
read the projection, so it cannot drive execution, recovery or admission
decisions.
