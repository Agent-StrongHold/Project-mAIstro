---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# #766 DAG execution Workspace scope

Adds six focused collected tests for the request-bound DAG Workspace selection seam. Three drive the seam directly: required selection/principal input, fail-closed unknown/non-member/archived selection, and successful authorization of an active member Workspace. Three drive the `/dags/{dag_id}/run` WebSocket boundary that calls the seam: an authorized member selection reaches the accepted socket, a selection the principal cannot use is refused with 1008 before `accept()`, and a whitespace-only selection follows the transitional omitted-id path. Multiple negative assertions live inside the same collected test because they are branches of one authority rule, not independent behaviors. Net collected-test movement is exactly +6.
