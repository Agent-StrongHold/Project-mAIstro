---
inventory-delta:
  tests/: +3
---

# CI repair: coverage-gate restore-oracle readiness race (#1152 lane)

CI run 39185684398 (merge-group evaluation of auto-1152@f30f05c25) failed the
`Coverage gate (publish-set floor + diff coverage)` job in its `combine` step:
the root-suite producer ended `5474 passed, 138 skipped, 4 errors`, and all
four errors were `tests/test_restore_oracle_characterization.py` cases failing
at the module fixture — `docker exec … psql … CREATE TABLE` exited 2 because
`_wait_ready` accepted a single `pg_isready` success, which the official
postgres entrypoint answers during initdb's temporary-server phase, before the
real server exists.

The repair keeps all four live characterization cases (they pass unchanged)
and hardens the fixture: `_wait_for_postgres` now requires the entrypoint's
"PostgreSQL init process complete" log marker AND a real `SELECT 1` round-trip.
Three unit tests are added for the polling helper itself, none needing Docker:

1. probe success without the init marker must not end the wait (the exact CI
   defect, now pinned — a regression to probe-only readiness fails this test);
2. the marker → restart-gap → SQL-ready sequence is fully consumed before the
   wait returns (no early return, no hang);
3. a server that never becomes ready fails the fixture loudly instead of
   hanging into pytest-timeout.
