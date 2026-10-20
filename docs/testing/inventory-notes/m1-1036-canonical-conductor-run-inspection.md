---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# M1 #1036 canonical Conductor Run inspection

Conductor's DAG-run inspection answers from canonical truth: the list/detail
routes serve the `DagRunStore` projection page with the canonical Run's
lifecycle overlaid wholesale through the scoped `ScopedRunReader` (#1152,
#1877) — status, result, error and finished_at all come from the canonical
Run whenever it is readable — and by canonical ID a Run from any producer
that left no projection row at all is answered directly from the canonical
spine: inspectable and controllable under the same id, with recent-list
discovery staying projection-gated per #1036's read-contract boundary. The
control route reaches `RunExecutionService.cancel_run` through the canonical
id (projection row mapping or the by-ID answer itself), refusing with 503
when no canonical spine is wired (ADR-082826-d9f5).

After the develop sync, this lane's slice is proven by
`test_canonical_run_inspection.py` (three tests):

- `test_a_projectionless_canonical_run_is_inspectable_and_controllable_by_id`:
  a Run created through the real canonical producer seam
  (`RunExecutionService.create_run` over a scoped `InMemoryRunStore` — the
  same handoff surface Builders/schedule/Evolve adapters use) with NO
  Conductor projection row is inspected by canonical id, cancelled through
  the public cancel route onto the canonical Run (which never gains a
  projection row), absent from recent-list discovery by design, and refused
  to a foreign observer exactly like a missing id.
- `test_a_stale_projection_row_overlays_canonical_truth_and_stays_scoped`:
  when the projection row exists, list and detail serve the canonical Run's
  status/result over the row's stale "running", with NodeRun/Attempt
  evidence filed in the same spine and no visibility outside the producing
  Workspace.
- `test_standalone_projection_is_presentation_only` pins the ADR-082826-d9f5
  bridge-less policy end-to-end (see the closeout note).

The wider canonical overlay, cancel-route, SSE-scope and creative-lineage
behaviors are pinned by the develop-side suites
(`test_dag_run_cancel_route.py`, `test_dag_run_canonical_lifecycle.py`,
`test_dag_run_scope.py`, `test_dag_run_creative_inspection.py`).
