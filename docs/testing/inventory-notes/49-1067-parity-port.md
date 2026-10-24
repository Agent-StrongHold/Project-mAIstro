---
inventory-delta:
  packages/maistro-core/tests: +9
---

# Issue #49 repair: port the #1067 canonical-vs-legacy parity fixes

Issue: #49
Parent: #14

## What moved and why

The #49 cutover (cac5ee2eb) made `CanonicalGraphPipelineExecutor` the
production Builders execution authority on this branch, but the branch base
predates the two develop commits that fix the #1067 canonical-adapter parity
defects (`7a65ee24f` defect 2; `fc6a7eb46` defects 1/3/4). A false-completion
reproduction against the pre-repair branch head confirmed the acceptance gap.
This round ports those fixes, and the +9 node IDs are their regression
coverage — all in `packages/maistro-core/tests`:

- `builders/test_canonical_execution.py` +8:
  `test_revision_dominates_a_concurrent_wave_after_it_settles` and
  `test_revision_dominates_a_concurrent_wave_with_an_immediate_dispatcher`
  (defect 1: revision invalidation folds after the wave settles, per-frontier
  flush); `test_stale_guard_defer_does_not_survive_a_genuine_later_failure`
  (stale-guard marker must not mask a real failure);
  `test_gate_without_revise_target_reoffers_itself_and_records_new_evidence`
  (defect 2: a gated node with no `revise_target` revises itself instead of
  false-completing the Run); `test_two_concurrent_stage_failures_project_...`
  (defect 4: receipt stage name and error come from the same authoritative
  failure); `test_derived_max_steps_covers_a_representative_wide_pipeline`,
  `test_derived_max_steps_covers_repeated_revision_driven_free_frontiers`,
  and `test_execute_derives_and_passes_a_sufficient_max_steps` (defect 3:
  the durable walk bound is derived from Builders' own budget, not the
  generic 256-step default).
- `graph/durable_runs/test_executor_gaps.py` +1:
  `test_public_entry_point_honors_an_explicit_max_steps_override` (the
  `max_steps` seam `run_durable_graph`/`resume_durable_graph` expose).

Counted by `pytest --collect-only -q`: `test_canonical_execution.py` 15 → 23,
`test_executor_gaps.py` 21 → 22.
