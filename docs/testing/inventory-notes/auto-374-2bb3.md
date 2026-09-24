---
inventory-delta:
  tests/: +6
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

A second develop merge (8bb344e32) then moved the root suite again: new files
(`tests/test_check_durable_table_inventory.py`, `tests/test_ratchet_base_rev_policy.py`,
`tests/migrations/test_audit_scope_migration.py`) and edits to existing ones changed the
collected node set by +2 relative to the ledger as recorded above. All six touched files
collect cleanly (102 nodes, no errors); the drift is merge-shaped, not a silently lost suite.
That +2 absorbs into this same note: −3 + 2.

Net recorded delta: −1. Produced by `check-suite-inventory.py --update`, not estimated.

## Repair follow-up (corpus honesty, second wave)

Independent re-verification flagged that the corpus honesty standard enforced on the three
originally parametrized documents was not applied to seven more specs that received the identical
front-matter-only move (Proposed ADR from `substrate`/`implements` into `related`) with the
present-tense governing prose left intact: SPEC-070226-6489 (ADR-084), SPEC-070226-82ea (ADR-099),
SPEC-070226-b234 (ADR-086), SPEC-070226-b624 (ADR-071), SPEC-070226-c4f8 (ADR-101),
SPEC-070226-cb8d (ADR-079), SPEC-070226-fbe3 (ADR-081). The repair rewords each document's prose
to mark the Proposed ADR as retained design context rather than shipped authority, and extends the
same parametrization over them: 3 collected nodes → 10, i.e. +7. Net for this note: −1 + 7 = +6.
A corpus-wide sweep for `ADR-* (specifies|mandates|says)` against active specs now returns only
these repaired documents plus SPEC-080126-3a7c (itself Superseded — a non-active source, outside
the gate's scope by design). Produced by `check-suite-inventory.py --update`, not estimated.
