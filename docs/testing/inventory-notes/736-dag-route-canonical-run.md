---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# #736 DAG route canonical execution

Records this branch's collected-node delta for
`packages/hive-conductor/backend/tests`: +3 here plus +1 in
`auto-736-0a8f.md` (net +4) — the canonical-route rewrite replaced the
route's old execute_dag-shaped tests and added the #736 coverage below.

Route/projection coverage added or rewritten for the canonical path:

- The shipped CRUD-created, role-shaped DAG driven through
  `POST /v1/dags/{dag_id}/run`, comparing the canonical Run store row with the
  `DagRunStore` projection (one execution identity, both stores).
- A registered DAG through the same route with `graph_runner.execute_dag`
  monkeypatched to raise: the legacy direct executor must not be called.
- A canonical node that fails during execution cannot be projected as a
  completed DAG run.
- A registration rejection (unknown node kind) fails before any Run is
  admitted or named — no fake `run_id`/`execution_id`, public failure text.
- A history-store failure during projection does not rewrite the executed
  outcome.
- A no-query run of an unscoped CRUD DAG admits into the authenticated
  owner's single Workspace, not the deployment default.
- A real HITL node (`human.ask_question`) parks the canonical Run as
  `paused`; the projection stays non-terminal with no completed node state.

The waiting/paused mapping of the projection helper is additionally covered by
a fabricated-input unit test (`test_projection_preserves_a_waiting_canonical_run`);
the HITL test above drives the pause through a real route execution.

# Deferral: the DagBuilder WebSocket Run button

The shipped DagBuilder Run button opens `/v1/ws/dags/{id}/run`
(`routes/ws.py::stream_dag_run`), a separate producer that still executes
through `graph_runner.execute_dag_streaming`. #736's collision boundary names
only `routes/dags.py` among route files, and the issue defers "final
retirement/demotion of other Conductor lifecycle projections after every
producer uses canonical execution" to parent #53. A prior branch state moved
that socket onto `routes.dags._execute_registered_dag` with matching
coverage (`test_ws_run_button_executes_one_canonical_run`); verification
ruled the `routes/ws.py` diff outside the boundary, so both were reverted
here (salvage patch: `../salvage-736/ws-convergence-deferred.patch`, also
preserved in branch history). The WS convergence — including its
`test_ws_auth.py` coverage — belongs to #53 with `routes/ws.py` added to its
may-modify list.
