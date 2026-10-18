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

`test_a_run_from_the_producer_seam_is_inspectable_by_canonical_id` replaces
source-probe-only parity evidence for the Conductor-observer half of the
cross-product requirement: a Run created and executed through the real
canonical producer seam (`RunExecutionService.create_run`/`execute_node` with
`PythonExecutionRuntime` over a real scoped `InMemoryRunStore` — the same
handoff surface Builders/schedule/Evolve adapters use) is listed and
inspected by `dag_run_inspection` under the same canonical run id — canonical
status/result overlaid onto the projection row, NodeRun and Attempt evidence
filed in the same spine — and is invisible to an observer outside the
producing Workspace. The full strict #459 closeout (real stores across every
product boundary, zero abstentions) remains owned by #459.

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
