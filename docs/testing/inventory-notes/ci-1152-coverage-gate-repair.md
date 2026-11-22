---
inventory-delta:
  tests/: +3
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +1
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

The diff-coverage half of the same gate (it never reached in that run, the
combine step having died) was then reproduced locally and found two real gaps
in the branch's own changed lines, both closed with evidence:

- `maistro/security/sentinel/authz_types.py` `Principal.__post_init__` refusals
  were never exercised: `test_authz_tier_ladder.py` gains two cases (blank id,
  agent without owner) — `packages/maistro-core/tests +2`;
- `maistro_server/api/runs.py` `get_run_boundary()`'s 503 arc was never taken:
  `test_runs_api.py` gains the store-configured/boundary-absent refusal for
  reads, cancellation and node-run listing — `packages/maistro-server/tests
  +1`.

After both, the gate reports `ok` over every measured file this change
touches (core runs/graph/security suites with live PostgreSQL legs, plus the
full maistro-server suite), and the root-suite producer that failed in CI
ends `5480 passed, 138 skipped` with the four oracle errors gone.

Recovered prior-attempt work (applied into this worktree uncommitted, 21:46
local): `create_container` now provisions the configured Workspace and its
`dev` owner at composition (#1152 review), so the Run read boundary's
membership rows exist from first boot, and `test_chat_completions.py` drops
its test-side bootstrap accordingly. Its wiring test is joined by three
provisioning-contract cases (idempotent restart, lost create race, fail-loud
fault) — `packages/maistro-core/tests +4` total with the fresh-container
case, `+2` for the authz cases above. `create_container` stayed under the
ruff C901 ceiling by extracting `_provision_configured_workspace`.
