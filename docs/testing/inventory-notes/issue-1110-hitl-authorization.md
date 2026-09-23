---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue 1110 HITL authorization

Adds end-to-end reviewer isolation coverage for canonical Project grants/denies, payload isolation, answer/cancel settlement, actor-only denial audit evidence, and two-principal Workspace-scoped expiry.

## Merge reconciliation (develop `ba2f1f077`)

Develop landed #1275's bounded discovery fairness (keyset walk in
`/pending`) and #1455's security-rejected attribution/redaction after this
branch forked. The merge composes them rather than choosing: `/pending` now
keyset-walks inside each *authorized Project* (not just each Workspace), so
#1109's fairness and #1110's authorization both hold; `/expire` keeps the
caller-scoped, actor-attributed tick. Develop tests that seeded pauses under
the fixture's fake default Project were re-seeded into each Workspace's
canonical root Project, and the settlement suite's `_OverEagerIndexStore`
fake was widened to the store protocol's `project_ids`/`workspace_ids`
signature — discovery and settlement now only ever see canonical scopes.

## Re-validation after the develop `84d937add` merge

The `84d937add` merge (audit org scope, DagBuilder runs surface) touched no
HITL path; the merged head was re-validated: 27/27 door+timeout tests,
32/32 core settlement tests, ruff/format, mypy on the durable_runs modules,
and the `check-{enumerations,public-routes,suite-inventory,security-inventory,owned-store-access,agent-store-writes}` gates. A manual
mutation check (no-op `authorize_project`, authentication intact) fails
exactly the two isolation tests, confirming the suite detects removed scope
checks.

## Repair-phase re-validation (head `ef24661fe`)

The 2026-09-23 repair pass found the tree already implementing the branch's
scope model and re-proved it from scratch at the assigned head (no check logs
had been produced by the driver): 27/27 door+timeout tests, 430 passed /
21 skipped in `maistro-core` durable_runs, the full hive-conductor backend
suite (2567 passed / 1 skipped), ruff check + format clean, mypy clean across
all six package sources (711 files), and the `check_enumerations`,
`check-enumerations-provenance`, `check-public-routes`, `check-suite-inventory`,
`check-security-inventory`, `check-owned-store-access`, and
`check-agent-store-writes` gates. The mutation check was re-executed live:
no-op'ing `authorize_project` (authentication intact) fails exactly
`test_hitl_routes_are_scoped_to_the_callers_workspaces` and
`test_project_reviewer_isolated_from_sibling_hitl_work`; restoring the
function returns the suite to 27/27. Inventory delta re-counted against the
develop base: exactly +2 test functions in
`packages/hive-conductor/backend/tests`.

## Independent repair re-validation (head `1e9a82cf7`)

The successor repair worker (the prior attempt died on a provider 429 before
running anything) re-executed the full battery at the assigned head, not
trusting the record above: 27/27 door+timeout tests, 430 passed / 21 skipped
in `packages/maistro-core/tests/graph/durable_runs`, the full hive-conductor
backend suite (2567 passed / 1 skipped), `ruff check` + `ruff format --check`
clean, canonical mypy clean (711 files), all seven gates listed above green,
and the same live mutation check reproduced — no-op `authorize_project`
fails exactly the two isolation tests, revert restores 27/27 with a clean
tree.

## Post-merge repair re-validation (head `8b949893f`)

The next repair worker re-proved the branch at the merge head that composes
develop `8bb344e32` (no driver check logs existed for this job either):
27/27 door+timeout tests, 430 passed / 21 skipped in
durable_runs (`test_hitl_settlement.py` 32/32), the full hive-conductor
backend suite at this head (2655 passed / 1 skipped), `ruff check` +
`ruff format --check` clean, mypy clean over the 17 `durable_runs` sources,
and the `check_enumerations`, `check-public-routes`, `check-suite-inventory`,
`check-security-inventory`, `check-owned-store-access`, and
`check-agent-store-writes` gates green. The live mutation check was executed
again at this head: no-op `authorize_project` (authentication intact) fails
exactly `test_hitl_routes_are_scoped_to_the_callers_workspaces` and
`test_project_reviewer_isolated_from_sibling_hitl_work`; the precise edit
restore returns 27/27 with a clean tree. The `inventory-delta` count was
re-verified against the develop base: exactly +2 test functions
(20→21 door, 5→6 timeout/cancel).

## Independent verifier re-validation (head `b3b4ccfd8`)

This pass re-proved every acceptance criterion from reachable behavior,
trusting neither the prior result artifact nor the entries above (the driver
again produced no check-*.log files): `ruff check` + `ruff format --check`
clean; 27/27 door+timeout tests; 430 passed / 21 skipped in
durable_runs; the `check_enumerations`, `check-enumerations-provenance`,
`check-public-routes`, `check-suite-inventory`, `check-security-inventory`,
`check-owned-store-access`, and `check-agent-store-writes` gates green; mypy
clean over the 17 `durable_runs` sources. The mutation check was executed
live once more at this head with the same result: a no-op `authorize_project`
(authentication untouched) fails exactly the two isolation tests; the exact
edit reverted, `git status`/`git diff` clean, 27/27 restored. The
`inventory-delta` count was recomputed from `git show` of the develop base:
still exactly +2 test functions (20→21 door, 5→6 timeout/cancel).

