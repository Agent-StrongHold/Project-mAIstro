---
inventory-delta:
  packages/maistro-rsi/tests: +3
---
# 1792-fail-first-gate-complexity-refactor

## What changed

Issue #1792 refactored the six complexity blocks regressed or created by
#1730 in `packages/maistro-rsi` down under the C ceiling (complexity ≤ 10)
without transferring equivalent complexity into new helpers:

- `fail_first.py`: `collect_fail_first_evidence` C(12) → B(6),
  `_has_related_failure` C(14) → B(9), `fail_first_gate` C(11) → B(6), via
  extracted seam helpers (`_resolve_evidence_shas`, `_tree_states`,
  `_reconstruct_tree`, `_run_base_probes`, `_reproducible`,
  `_test_module_imports`, `_references_changed_module`,
  `_valid_evidence_result`, `_behavior_contract_result`,
  `_refactor_contract_result`, `_characterization_contract_result`).
- `candidate_fitness.py`: `compose_scorecard` D(23) → A(2),
  `evaluate_candidate` C(20) → B(8), via `_scorecard_gates`,
  `_scorecard_scores`, `_reason_gate`, `_quality_delta`, `_new_test_score`,
  `_objective_scores`, `_work_scores`, `_changed_py_partition`,
  `_baseline_derived`.
- `local_loop.py::LocalRsiLoop._fitness_decision` was already B(10) at this
  branch's implementation base (improved by work banked before it), so no
  code change was needed; verified and covered by the existing suite.

All six values above are `radon cc` 6.0.1 measurements re-taken at the final
head of this branch (the develop-sync merge commit that carries the refactor);
they match the tree, not an intermediate state.

## Test delta

Three focused tests added to `packages/maistro-rsi/tests/test_fail_first.py`,
covering the negative and malformed evidence paths that the refactor moved
into new helpers and that no existing test pinned:

1. `test_related_detection_falls_back_to_textual_imports_when_the_test_file_is_malformed`
   — an unparsable failing test still gets the attribution check through the
   textual import-line fallback (malformed evidence is attributed, not
   dropped).
2. `test_related_detection_skips_unreadable_test_files_without_inventing_relatedness`
   — an unreadable failing test is neither related nor a crash; the guard
   fails the check without manufacturing relatedness.
3. `test_probe_returns_missing_evidence_when_the_base_ref_is_unresolvable`
   — an unresolvable baseline ref yields no evidence at all (the gate fails
   the behavior contract closed on missing) and touches nothing in the
   candidate tree.

Behavior preservation itself is pinned by the pre-existing 37
`test_fail_first.py` tests (red→green proof, flaky red, config taint,
unrelated failure, candidate deletion, new-module test-first), the
`test_candidate_fitness.py`/`test_candidate_fitness_scenarios.py` scorecard
and promotion matrices, and `test_local_loop.py`.
