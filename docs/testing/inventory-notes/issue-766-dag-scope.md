---
inventory-delta:
  packages/hive-conductor/backend/tests/test_dag_execution_scope.py: rewritten for canonical admission
  packages/hive-conductor/backend/tests/test_dags_routes.py: +workspace-scoped run setup
  packages/hive-conductor/backend/tests/test_ws_auth.py: +workspace-scoped socket setup
  packages/hive-conductor/backend/tests/test_canonical_dag_runner.py: +immutable scope coverage
  packages/hive-conductor/backend/tests/test_graph_runner.py: +immutable scope setup
  packages/hive-conductor/backend/tests/test_optimizer.py: +workspace-scoped optimizer setup
  packages/hive-conductor/backend/tests/test_dag_condition_trust.py: +execution scope
  packages/hive-conductor/backend/tests/test_dag_recovery.py: +execution scope
  packages/hive-conductor/backend/tests/test_dag_run_history_durability.py: canonical scope seam fixture
  packages/hive-conductor/backend/tests/test_dag_run_scope.py: canonical Root Project assertion
---
# issue-766-dag-scope

The DAG execution tests now exercise canonical WorkspaceStore membership and
Root Project resolution rather than seeding the retired `stores.workspaces`
JsonStore. HTTP and WebSocket controls pass the same immutable
`DagExecutionScope`, and omission/unauthorized selections are refusal cases.
Existing canonical adapter and streaming tests were updated to provide an
explicit scope because compatibility scope fallback is no longer an execution
admission path.
