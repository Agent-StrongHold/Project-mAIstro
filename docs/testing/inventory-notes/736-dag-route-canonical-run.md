---
inventory-delta:
  packages/hive-conductor/backend/tests: -1
---

# #736 DAG route canonical execution

Adds three focused route/projection tests. The first drives a real registered DAG through
`POST /v1/dags/{dag_id}/run` with an authorized Workspace, then compares the
canonical Run store row and the `DagRunStore` projection. The second executes a
canonical node that fails during execution and proves the projection remains
failed rather than reporting completion. The third proves a waiting canonical
Run is projected as waiting with a running node, not as a failure.
