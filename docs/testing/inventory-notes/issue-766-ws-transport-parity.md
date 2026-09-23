---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# issue-766-ws-transport-parity

Adds `test_dag_execution_transport_parity.py` (6 tests, #766). They check that
the DagBuilder Run socket and `POST /v1/dags/{id}/run` behave the same way:
two Workspaces created through `POST /v1/workspaces` produce two different
canonical Runs, each with its own Workspace and Root Project and its own
`DagRunStore` projection. A failed node gives the same status and error on WS
and HTTP. An unexpected failure frame (infrastructure error or malformed DAG)
shows only the exception kind. A Workspace the caller is not a member of is
refused on HTTP before any Run exists. A SQLite-backed canonical
`WorkspaceStore` with no `stores.workspaces` row lets a member run and refuses
a non-member on both transports. Only the model boundary
(`graph_runner._build_llm_call`) and, in one test, the durable graph driver
are replaced. No existing test was removed or moved.
