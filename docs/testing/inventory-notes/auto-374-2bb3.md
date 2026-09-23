---
inventory-delta:
  tests/: -3
---

# auto-374-2bb3

Reconciliation for the auto-374 lane after merging develop (ba2f1f077) and the
#374 citation repair on top of it.

The merge carried root-suite edits from develop (notably `tests/test_m1_542_diff_coverage_edges.py`,
`tests/test_prepull_copy_sources.py`, `tests/test_verify_wheel_imports.py`) whose collected
node counts moved relative to what each parent's notes had recorded — a merge-shaped drift
the per-change ledger absorbs here rather than on either parent. That drift is −5.

On top of it, this repair parametrized
`test_proposed_related_design_is_marked_historical_not_governing` over the three documents
where an Accepted spec treated a Proposed ADR as governing prose (SPEC-070226-af02/ADR-066,
SPEC-070226-2b70/ADR-055, SPEC-062126-d421/ADR-083): 1 collected node → 3, i.e. +2.

Net recorded delta: −3. Produced by `check-suite-inventory.py --update`, not estimated.
