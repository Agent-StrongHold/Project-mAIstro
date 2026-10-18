---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# M1 #1036 canonical Conductor Run inspection

Conductor's DAG-run inspection answers from canonical truth: the list/detail
routes serve the `DagRunStore` projection page with the canonical Run's
lifecycle overlaid wholesale through the scoped `ScopedRunReader` (#1152,
#1877) — status, result, error and finished_at all come from the canonical
Run, so the projection row can never contradict Run truth. The control route
reaches `RunExecutionService.cancel_run` through the projection row's
`canonical_run_id` mapping, refusing with 503 when no canonical spine is
wired (ADR-082826-d9f5).

After the develop sync, this lane's slice is proven by
`test_a_run_from_the_producer_seam_is_inspectable_by_canonical_id`: a Run
created and executed through the real canonical producer seam
(`RunExecutionService.create_run`/`execute_node` over a scoped
`InMemoryRunStore` — the same handoff surface Builders/schedule/Evolve
adapters use) is listed and inspected by `dag_run_inspection` under the same
canonical run id, with the canonical status/result overlaid onto the stale
projection row, NodeRun/Attempt evidence filed in the same spine, and no
visibility for an observer outside the producing Workspace. The wider
canonical overlay, cancel-route, SSE-scope and creative-lineage behaviors are
pinned by the develop-side suites (`test_dag_run_cancel_route.py`,
`test_dag_run_canonical_lifecycle.py`, `test_dag_run_scope.py`,
`test_dag_run_creative_inspection.py`).
