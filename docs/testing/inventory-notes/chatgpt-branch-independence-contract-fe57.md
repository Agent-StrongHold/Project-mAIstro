---
inventory-delta:
  tests/: +21
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
