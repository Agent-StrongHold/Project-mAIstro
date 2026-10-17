---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# Epic #14 round 2 — Conductor inspection closeout + cross-product observer

Second round on the #1036 slice of epic #14, resolving the prior
NEEDS-DEEP-REVIEW findings that were actionable in this lane.

## Standalone projection closeout (ADR-082826-d9f5)

`test_standalone_projection_is_presentation_only` pins the reviewed
deployment policy for the bridge-less compatibility path: with no canonical
RunStore wired, the retained `DagRunStore` projection may serve scoped reads
(list/detail inside the caller's Workspace universe), but `cancel_visible_run`
refuses (returns None) rather than mutating product history — the projection
has no terminal authority and can neither terminalize nor resurrect a Run.
The policy is now stated explicitly in the `dag_run_inspection` module
docstring so the boundary is reviewed content, not an implicit fallback.

## Real cross-product producer → spine → Conductor observer

`test_a_run_from_the_producer_seam_is_inspectable_by_canonical_id` replaces
source-probe-only parity evidence for the Conductor-observer half of the
cross-product requirement: a Run created and executed through the real
canonical producer seam (`RunExecutionService.create_run`/`execute_node` with
`PythonExecutionRuntime` over a real scoped `InMemoryRunStore` — the same
handoff surface Builders/schedule/Evolve adapters use) is listed and inspected
by `dag_run_inspection` under the same canonical run id, including NodeRun and
Attempt evidence, and is invisible to an observer outside the producing
Workspace. The full strict #459 closeout (real stores across every product
boundary, zero abstentions) remains owned by #459.

## Not resolved in this round (owned elsewhere, recorded for the verifier)

- `scripts/check-shipped-surface-truth.py --require-clean` still fails on
  seven production-enabled unresolved facades; each was re-verified against
  its code and its classification remains truthful. Owners: #382 (deferred
  outside M1), #286, #389, #766.
- `scripts/check-execution-lifecycles.py` now passes (baseline resolves to
  `0ab0bb698`, candidate `27ba4f933`); the prior failure was the uncommitted
  working tree resolving the baseline to itself.
