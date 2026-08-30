---
inventory-delta:
  tests/: +3
---
# claude-issue-497-develop-test-job-red

Three new tests in `tests/test_m1_convergence_freeze.py`, all covering
`_fetched_base` — the helper that resolves the PR base revision the live
convergence-freeze comparison runs against.

Two drive it with a recording stand-in for `subprocess`: an existing
remote-tracking ref is used as-is with no fetch, and a missing one is fetched
shallowly and compared against `FETCH_HEAD`. The third runs it against this
repository's real clone, because a helper that returns a revision `git` will not
accept would satisfy both of the others.

Nothing was removed or renamed. The other two fixes in this change repair
existing tests rather than adding any.
