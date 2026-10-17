---
inventory-delta:
  tests/: -1
---

# #860 pinned develop merge: overlapping wheel-verifier regression

The inherited merge of `e46ad6708fda20f76b8915679ef701f3ddb6b7e2` into
`0a40bbb7d541bc283c67592a62289780e0ec160d` conflicted in
`tests/test_ci_merge_group_scope.py`. Each parent added the same three
assertions for `classify(["scripts/verify-wheel-imports.py"])`: wheel imports
and Docker enabled, PostgreSQL disabled. The names differed only by
`wheel_imports_verifier` versus `wheel_import_verifier`.

Keep the develop spelling (`test_wheel_import_verifier_change_runs_wheel_imports_leg`)
and all three assertions once. This preserves both parents' behavior without
inventing a duplicate test merely to satisfy additive inventory accounting.
The develop addition is recorded in `auto-975-wheel-imports-scope.md`; the
merged notes counted the overlapping addition twice.

Fresh `uv run python scripts/check-suite-inventory.py --suite tests/` after
resolving the conflict collected **5,116** tests versus **5,117** expected.
This -1 note reconciles that overlap; it does not waive a collection error.
The focused execution including the conflict file and #860 production-seam
regressions passed **121 tests**. No test assertions or CI selection gates
were weakened.
