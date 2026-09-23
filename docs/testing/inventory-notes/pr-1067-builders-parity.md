---
inventory-delta:
  packages/maistro-core/tests: +5
---
# pr-1067-builders-parity

Issue #1067 fixes 4 canonical-vs-legacy Builders parity defects found by a
post-merge audit of #734/#744 and adds focused regression coverage for each:

- `packages/maistro-core/tests/builders/test_canonical_execution.py`:
  - `test_revision_dominates_a_concurrent_wave_after_it_settles` (defect 1 —
    same-wave revision invalidation now folds after the wave settles instead
    of racing a slower sibling's own commit).
  - `test_two_concurrent_stage_failures_project_one_consistent_authoritative_failure`
    and the rewritten `failed` case in
    `test_projection_maps_running_queued_and_non_failed_terminal_node_runs`
    (defect 4 — the compatibility receipt now derives the failed stage and
    its message from the same canonical-selected failure).
  - `test_derived_max_steps_covers_a_representative_wide_pipeline` and
    `test_execute_derives_and_passes_a_sufficient_max_steps` (defect 3 — the
    durable walk step bound is now derived from Builders' own admitted
    pipeline size/iteration policy instead of the generic default).
- `packages/maistro-core/tests/graph/durable_runs/test_executor_gaps.py`:
  - `TestStepBudgetExhaustion::test_public_entry_point_honors_an_explicit_max_steps_override`
    (defect 3 — the public `run_durable_graph`/`resume_durable_graph` entry
    points now accept an optional `max_steps`, the canonical seam that
    defect 3's fix needed).

Defect 2 (a gated node with `revise_target=None`) was already fixed on
`develop` by an unrelated commit (7a65ee24) before this audit's fix landed;
the existing `test_gate_without_revise_target_reoffers_itself_and_records_new_evidence`
already locks the correct behavior, so no new test was needed for it.

Net: +5 collected node IDs in `packages/maistro-core/tests`.
