---
inventory-delta:
  tests/: +24
---
# 1351-pr-scope-policy-parity

Twenty-four new node IDs pin the converged pull-request scope policy from #1351:
one classifier (`scripts/ci_merge_group_scope.py::classify`) now governs PR
events across every surface — the ci.yml specialized job conditions,
`check-integration-scope.required_checks`, the classifier's own
`scope_for_event`/`scope_from_environment` event API, and the gates-ran
evaluator's changed-file envelope derivation.

Eight of them live in the new `tests/test_pr_scope_policy_parity.py`, the
cross-surface contract: all four surfaces derive the same scope for one
measured PR file set, ci.yml conditions produce the same verdict as the
required-check set leg by leg, the evaluator loads the checked-in classifier
module (not a copy), and the documented gates-ran outcomes are pinned (a
docs-only PR whose specialized jobs skipped per the classifier publishes green;
a skipped check whose leg is in scope stays red).

Fourteen replace or extend tests that pinned the old, divergent policy:
`test_ci_merge_group_outputs` now asserts PRs classify measured changed paths
and fail closed without diff evidence while protected pushes stay unconditional;
`test_ci_specialized_scope_wiring` evaluates the rewritten job conditions with
a small GitHub-expression evaluator (truth tables for pull_request and develop
merge groups, unconditional escapes for pushes and foreign merge bases) instead
of substring guards, and adds the PR twin of the postgres matrix constraint;
`test_check_integration_scope` parametrizes the fail-closed scope handling and
the skip-is-acceptable-only-out-of-scope rule over both candidate events.

No test was deleted; one assertion-bearing test per surface was rewritten in
place (`test_pull_request_preserves_all_specialized_checks`,
`test_pull_request_skipped_check_is_a_finding`,
`test_specialized_scope_gates_preserve_required_matrix_contexts`,
`test_pull_request_keeps_every_specialized_leg_enabled`), so the net count is
purely additive.

Two further node IDs landed with the review follow-ups and complete the
policy's producer side: `test_verifier_change_runs_wheel_leg`
(`tests/test_ci_merge_group_scope.py`) pins that the wheel-imports leg fires
when its own verifier script changes — the same gate-script-must-run-its-own-leg
rule the floor-install gate test asserts — and
`test_hive_e2e_scope_covers_the_jobs_actual_inputs`
(`tests/test_ci_merge_group_outputs.py`) pins the widened `hive_e2e`
predicate to the jobs' real inputs (prepull script, bootstrap/canvas/design/
evolve trees), so a PR touching only those can no longer skip live-stack
validation while the evaluator would have excused the skip.
