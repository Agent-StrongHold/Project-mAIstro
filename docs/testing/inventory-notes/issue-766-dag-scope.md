---
inventory-delta:
  packages/hive-conductor/backend/tests: +20
---
# issue-766-dag-scope

The DAG execution tests now exercise canonical WorkspaceStore membership and
Root Project resolution rather than seeding the retired `stores.workspaces`
JsonStore. HTTP and WebSocket controls pass the same immutable
`DagExecutionScope`, and omission/unauthorized selections are refusal cases.
Existing canonical adapter and streaming tests were updated to provide an
explicit scope because compatibility scope fallback is no longer an execution
admission path.

Closing the develop-forward merge's diff-coverage gap on the changed lines in
`dag_execution_scope.py`, `canonical_dag_runner.py`, `routes/optimizer.py`,
`services/substrate_tools.py`, and `services/validation_gate.py` added
+20 collected node IDs:

- `test_dag_execution_scope.py`: `DagExecutionScope.__post_init__`'s three
  blank-field guards, and `authorize_hive_dag_scope`'s explicit-`project_id`
  branch (an owned Root Project accepted, an unknown id refused, and a
  Project belonging to a different Workspace refused the same non-oracle way).
- `test_canonical_dag_runner.py`: `_scope`'s missing-scope and
  project-id-mismatch refusals, plus `execute_dag`'s own missing-scope guard
  and its `user_id`-does-not-match-scope guard.
- `test_optimizer.py`: `POST /v1/optimizer/{dag_id}/run` refuses an omitted
  Workspace selection (403, matching the DAG-run route's posture), and a full
  `validate=True` pass — real DAG in `stores.dags`, workspace-scoped baseline
  run, per-proposal validation, and the model/param hill-climb sweeps — drives
  the validation gate end to end instead of short-circuiting on an empty
  `stores.dags` lookup.
- `test_substrate_tools.py` (new file): `tool_run_workflow` and
  `tool_hill_climb` resolve and are refused by the same
  `authorize_hive_dag_scope` seam the HTTP/WebSocket routes use, covering the
  scope resolution and `execute_dag` call each of them added.
- `test_dags_routes.py`: one HTTP-level replication of the PM-workflow e2e
  spec's "activate and run a DAG" step (create → activate → run with an
  explicit Workspace selection) — the fix for the 403 regression in
  `tests/e2e/pm-workflow.spec.ts` was an omitted Workspace selection in the
  spec itself, not a route defect, so this pins the route's success path the
  spec now exercises for real.
