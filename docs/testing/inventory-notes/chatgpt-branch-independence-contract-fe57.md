---
inventory-delta:
  tests/: +24
---
# chatgpt-branch-independence-contract-fe57

Closes the diff-coverage gap the merged branch exposed against
`scripts/check-branch-independence.py`: 9 new node IDs in
`tests/test_branch_independence.py` (error branches of `load_registry`,
`registry_errors`, and its per-surface helpers — missing/duplicate ids,
empty paths, a legacy surface without a `target_kind`, a missing root)
and 12 in a new `tests/test_check_branch_independence_base.py`, which
builds real git repositories to exercise `base_registry` and `main()`:
the implicit-vs-explicit base fallback (including the merge-base
fallback this same branch adds), a registry absent or corrupt at the
base, and the CLI's pass/fail/evaluation-error exit codes. No existing
test moved or was removed.

A Codex review of this PR found `base_registry()` would send git's null
before-SHA (what a branch-creating push sends as `RATCHET_BASE_REV`)
straight to `git rev-parse`, failing every first push to a new branch
instead of falling back the way an unset variable does; and that no
test exercised `trusted_base_errors()` through `main()` with a real
populated base, only the pure helper in isolation. Three more node IDs
close both: `test_null_sha_env_var_falls_through_to_the_default_base`
and `test_null_sha_passed_explicitly_also_falls_through` pin the fix,
and `test_rejects_a_candidate_that_expands_the_trusted_legacy_freeze`
proves end-to-end that a candidate cannot authorize a new shared
aggregate by editing its own frozen list once a trusted base registry
is available.
