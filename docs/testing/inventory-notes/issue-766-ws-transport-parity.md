---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
---
# issue-766-ws-transport-parity

Adds `test_dag_execution_transport_parity.py` (9 tests, #766). They check that
the DagBuilder Run socket and `POST /v1/dags/{id}/run` behave the same way:

- On each transport, two Workspaces created through `POST /v1/workspaces`
  produce two different canonical Runs, each with its own Workspace, Root
  Project and `DagRunStore` projection.
- Both transports run in `interactive` mode and write a `dag_run` audit entry.
- The canonical result reaches the socket's projection hook before any
  NodeRun frame, so a client that disconnects mid-stream cannot drop it.
- A failed node gives the same status and error on WS and HTTP.
- An unexpected failure frame (infrastructure error or malformed DAG) shows
  only the exception kind.
- An unknown Workspace, or one the caller is not a member of, is refused on
  HTTP before any Run exists.
- A SQLite-backed canonical `WorkspaceStore` with no `stores.workspaces` row
  lets a member run in its Root Project and refuses a non-member on both
  transports.

Only the model boundary (`graph_runner._build_llm_call`) and, in one test, the
durable graph driver are replaced. No existing test was removed or moved.
