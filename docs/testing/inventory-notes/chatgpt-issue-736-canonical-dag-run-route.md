# #736 canonical DAG Run route claim

## Claim

The shipped `POST /v1/dags/{dag_id}/run` route still executes through the legacy `services.graph_runner.execute_dag` path and creates an unrelated `DagRun` history id with no canonical `Run` identity. The existing `services.dag_agents.run_registered_dag` service already performs registered-DAG projection, canonical Run admission, durable Graph execution, and canonical NodeRun/Attempt recording.

This branch will migrate only the shipped route and its UI/history projection onto that existing public seam. It will not modify the execution spine to accommodate Conductor.

## Implementation plan

1. Add focused route-level behavioral tests proving one UI run creates exactly one canonical Run and one `DagRun` projection naming the same execution.
2. Resolve real request user and Workspace/Project scope from existing authorized Conductor/runtime state rather than deriving identifiers from the DAG id.
3. Replace direct `execute_dag` execution in `routes/dags.py` with `run_registered_dag`.
4. Preserve `DagRunStore` as UI/history/SSE projection only, setting `canonical_run_id` to the canonical Run.
5. Derive terminal/suspended/failure projection from the canonical durable record so local history cannot contradict execution truth.
6. Keep current route result/event shape where canonical evidence permits it.
7. Prove a failed canonical node cannot become a completed DAG projection.
8. Run focused Hive tests and full required CI before merge.

## Collision boundary

Owned by this branch:

- `packages/hive-conductor/backend/routes/dags.py`;
- `packages/hive-conductor/backend/services/dag_run_store.py` only for narrow projection/correlation behavior if needed;
- focused Hive DAG route/history tests;
- this branch-specific evidence note.

Explicitly excluded:

- `packages/maistro-core/src/maistro/container.py`;
- `packages/maistro-core/src/maistro/runs/**` and #640;
- `packages/maistro-core/src/maistro/graph/durable_runs/**`;
- `packages/hive-conductor/backend/services/dag_agents.py` unless its already-public route-facing contract is demonstrably insufficient;
- `packages/hive-conductor/backend/services/foundation.py` and #629;
- task/workspace HTTP files owned by #730;
- HITL files owned by #739;
- Evolve files owned by #733;
- checkpoint work owned by #731/#741;
- Invocation/provenance, migrations, quality ratchets, and workflow YAML.

Before claiming, the open PR set was searched for both `routes/dags.py` and `dag_run_store.py`; neither path is named by another open PR. Issue #736 also had no assignee or prior comment.
