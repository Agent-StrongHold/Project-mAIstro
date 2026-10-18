---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# Epic #14 round 2 — Conductor inspection closeout + cross-product observer

Second round on the #1036 slice of epic #14, resolving the prior
NEEDS-DEEP-REVIEW findings that were actionable in this lane. Adapted after
the develop sync to the merged canonical seams.

## Standalone projection closeout (ADR-082826-d9f5)

`test_standalone_projection_is_presentation_only` pins the reviewed
deployment policy for the bridge-less compatibility path: with no canonical
RunStore or reader wired (`SimpleNamespace(run_store=None, run_reader=None)`
in the engine bridge), the retained `DagRunStore` projection may serve scoped
reads (list/detail inside the caller's Workspace universe), but the cancel
route refuses with 503 and the projection row is left exactly as it was —
the path has no terminal authority and can neither terminalize nor resurrect
a Run, and scope still holds with no canonical overlay invented. The policy
is stated explicitly in the `dag_run_inspection` module docstring so the
boundary is reviewed content, not an implicit fallback.

## Real cross-product producer → spine → Conductor observer

The Conductor-observer half of the cross-product requirement is proven
against real execution, in two parts (both in
`test_canonical_run_inspection.py`):

- `test_a_projectionless_canonical_run_is_inspectable_and_controllable_by_id`
  needs no projection row at all: a Run created through the real canonical
  producer seam (`RunExecutionService.create_run` with
  `PythonExecutionRuntime` over a real scoped `InMemoryRunStore` — the same
  handoff surface Builders/schedule/Evolve adapters use) is inspectable and
  controllable by its canonical id through `dag_run_inspection` and the
  public cancel route, which fences the canonical Run without ever writing
  a projection row; recent-list discovery stays projection-gated by design
  and a foreign observer gets the non-disclosing refusal.
- `test_a_stale_projection_row_overlays_canonical_truth_and_stays_scoped`
  covers the row-bearing page: canonical status/result overlaid onto the
  stale projection row, NodeRun/Attempt evidence filed in the same spine,
  no visibility outside the producing Workspace.

## Not resolved in this round (owned elsewhere, recorded for the verifier)

- `scripts/check-shipped-surface-truth.py --require-clean` still fails on
  six production-enabled unresolved facades; the set is byte-identical to
  develop's own (verified against `ab8b3737f`'s matrix), so none was
  introduced or resolved by this lane. Owners per the matrix: #382
  (deferred outside M1; containers build), #389 (mcp discover/scan, memory
  contradict, settings reload), #359 (RSI timer-status simulation).
- `scripts/check-execution-lifecycles.py` passes on the merged tree (the
  prior failure was the uncommitted working tree resolving the baseline to
  itself).
