---
inventory-delta:
  packages/hive-conductor/backend/tests: -1
---

# #736 DAG route canonical execution

Adds four focused route/projection tests. The first drives the shipped CRUD-created,
role-shaped DAG through `POST /v1/dags/{dag_id}/run` and compares the canonical Run
store row with the `DagRunStore` projection. The second drives a registered DAG
through the same route while forbidding the legacy direct executor. The third
executes a canonical node that fails during execution and proves the projection
remains failed rather than reporting completion. The fourth proves a waiting
canonical Run is projected as waiting with a running node, not as a failure.
