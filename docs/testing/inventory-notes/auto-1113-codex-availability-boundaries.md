---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# #1113 review: availability at the HTTP and health boundaries

Six behavioral cases for the Codex findings on the Graph-fallback retirement:

- `/v1/hitl/*` answers 503 `graph_execution_unavailable` when the canonical
  execution spine is absent, for all four handlers (`test_hitl_door.py`);
- `/health` reports `graph_execution_available` and counts it in `degraded`;
  `/health/ready` lists `graph_execution` without flipping `ready`
  (`test_api.py`, 2 cases plus one extended);
- `POST /v1/dags/run-champion` keeps the top-level `error` for a champion Run
  that ended failed / paused / cancelled (`test_dags_routes.py`, 3 parametrized
  cases).
