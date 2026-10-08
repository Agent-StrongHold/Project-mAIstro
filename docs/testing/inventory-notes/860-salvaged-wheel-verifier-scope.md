---
inventory-delta:
  tests/: +1
---

# #860 CI repair — preserve the incoming wheel-verifier trigger regression

Salvaged the pre-existing test in `tests/test_ci_merge_group_scope.py` and its
classifier repair. The production workflow invokes `verify-wheel-imports.py`
inside the conditionally selected `wheel-imports` job. A merge-group change to
only that verifier must enable the job, without falsely claiming PostgreSQL
impact; Docker validation remains enabled as before.

The added test asserts these classifier outputs. Regression validation executes
this test against the starting HEAD's classifier in memory, expecting its
wheel-import assertion to fail, then runs the working-tree test suite. No source
or test is deleted or overwritten for mutation validation. This is CI-selection
evidence only, not release-candidate soak acceptance.
