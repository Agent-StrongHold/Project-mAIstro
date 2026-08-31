---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# #766 DAG execution Workspace scope

Adds three focused collected tests for the request-bound DAG Workspace selection seam: required selection/principal input, fail-closed unknown/non-member/archived selection, and successful authorization of an active member Workspace. Multiple negative assertions live inside the same collected test because they are branches of one authority rule, not independent behaviors. Net collected-test movement is exactly +3.
