---
inventory-delta:
  packages/hive-conductor/backend/tests: +14
---
# auto-65 Goal inspection projection

#65 (M3) adds a Workspace-centric Goal inspection layer over the canonical
Run/Event stores rather than a second Run store or Goal authority. The new
tests drive `services.goal_inspection` and the `GET /v1/goals` route against
the real canonical Workspace authority, a real `InMemoryRunStore`, and the
scoped reader the routes use (the `authed_client` fixture style), not mocks.

Fourteen new tests, none removed or moved:

- one Goal with several sequential/concurrent Runs is ONE history, not
  duplicated pseudo-tasks;
- run identity and status in a Goal view are exactly what `visible_run_detail`
  serves — no translation, no second terminal status;
- a completed/failed Run is evidence: `goal_state` stays `not_recorded` and the
  disposition names execution, never a Goal verdict;
- the canonical human pause (PAUSED → waiting_human) and the canonical
  non-human parked state (WAITING) stay distinguishable;
- provenance naming a Goal without its exact revision projects nothing;
- ordinary runs mint no pseudo-Goal;
- a foreign Workspace's Goals are invisible and 404-shaped, by list and by id;
- a Goal view answers by id without semantic translation;
- subgoal lineage and child-run/delegation provenance surface in the view;
- selected Graphs come from canonical Graph ids, never the projection's dag_id;
- the projection is read-time and writes nothing (survives restart/reconnect);
- the `GET /v1/goals[/<id>]` routes are scoped and read-only.
