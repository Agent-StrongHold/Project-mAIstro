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


## Repair-lane re-validation (head `95613cec8`)

This pass re-proved the branch at the assigned head after the `750edd84d`
merge (no driver check-*.log files existed for the job). `ruff check` +
`ruff format --check` clean; 27/27 door+timeout tests; 32/32
`test_hitl_settlement.py`; the full hive-conductor backend suite (2655
passed / 1 skipped); canonical mypy clean (712 files); the
`check_enumerations`, `check-enumerations-provenance`, `check-public-routes`,
`check-suite-inventory`, `check-security-inventory`,
`check-owned-store-access`, and `check-agent-store-writes` gates green. The
mutation check was executed live in two parts at this head: (1) a no-op
`authorize_project` call in `_require_project_access` (authentication
untouched) fails exactly
`test_hitl_routes_are_scoped_to_the_callers_workspaces` and
`test_project_reviewer_isolated_from_sibling_hitl_work`; (2) dropping the
`project_ids`/`workspace_ids` filters from the `/expire` store tick fails
`test_expiry_endpoint_only_settles_authorized_workspace_projects`. Exact
edits restored, tree clean, 27/27 re-confirmed.

## #364 reconciliation merge re-validation (head `c85177741`)

The develop tip (`60862b6c5`, "WIP: [M2-A][#364] Enforce Workspace object
authorization on HITL list/answer/cancel routes") independently implemented
workspace-object HITL authorization and conflicted with this branch's #1110
work in seven files. The mid-merge state left by the crashed driver was
salvaged (backed up to the job directory first) and resolved so both layers
compose instead of competing: maistro-core `durable_runs` adopts #364's
canonical `HitlAuthorization` store API (typed effective-principal evidence,
live membership recheck inside `_mutate_hitl`, delegation evidence, `GET
/{run_id}/{node_id}` inspect door), while the route keeps #1110's Project
authority (`authorize_project` with `hitl.inspect/answer/cancel`),
intended-reviewer binding, and denial audit; `/pending` composes Workspace
membership + per-record live membership recheck before payload disclosure
(#364) with per-authorized-Project keyset walks (#1110/#1109), and `/expire`
keeps Project-level `hitl.cancel` narrowing by passing the lane's optional
`project_ids` filter through #364's `_due_candidates`. The expiry isolation
test develop seeded under the fixture default Project was re-seeded into the
Workspace's canonical root Project, and develop's spliced
`project_id == "project-hitl"` inspect assertion was corrected to compare
against the seeded record's canonical root Project id. Validation at the
merge head: 32/32 door+timeout tests, 505 passed / 21 skipped in
durable_runs, the full hive-conductor backend suite (2669 passed / 1
skipped), maistro-core full suite (10163 passed / 654 skipped / 1 xfailed),
`ruff check` + `ruff format --check` clean repo-wide, canonical mypy clean
(713 files), and the `check-public-routes`, `check-security-inventory`,
`check-shipped-surface-truth`, `check-reachability`,
`check-reachability-dispositions`, `check-convergence-matrix`,
`check-doc-links`, `check-suite-inventory`, `check-wiring-reads`,
`check-agent-store-writes`, `check-model-egress`, `check-cross-package-imports`,
`check-durable-table-inventory`, `check-execution-lifecycles`,
`check-contract-markers`, `check-ac-state`, `check-radon-baseline`,
`check-credential-authority`, and `check-owned-store-access` gates green.
Mutation checks at this head: (1) no-op `_require_project_access`
(authentication intact) fails exactly
`test_project_reviewer_isolated_from_sibling_hitl_work`; (2) dropping the
per-record `authorization.permits` disclosure recheck fails exactly
`test_pending_rechecks_membership_before_disclosing_payload`; exact reverse
edits restore the committed tree byte-for-byte and 32/32 pass.
`check-vulture-baseline` is red, but identically red on pure develop's tip
(verified in a scratch worktree: same 1432 findings, larger unbanked delta
including 121 pydantic + 63 hive-service NEW identities), i.e. pre-existing
trunk ledger drift outside this lane's scope. `inventory-delta` re-counted
against the new develop base `60862b6c5`: exactly +2 test functions in
`packages/hive-conductor/backend/tests` (2423 → 2425); core `durable_runs`
unchanged at 435.

## Independent verifier re-validation (head `5f397289d`)

This pass re-proved the branch at the assigned repair head (docs-only delta
over `c85177741`; the driver again produced no check-*.log files, and the
prior result artifact was not trusted). `ruff check` + `ruff format --check`
clean on all six changed sources; 32/32 door+timeout tests; 505 passed /
21 skipped in `maistro-core` durable_runs; mypy clean over the 17
`durable_runs` sources; the `check-public-routes`, `check_enumerations`,
`check-enumerations-provenance`, `check-suite-inventory`,
`check-security-inventory`, `check-owned-store-access`, and
`check-agent-store-writes` gates green; full hive-conductor backend suite
2669 passed / 1 skipped. The mutation check was re-executed live with a new,
sharper result: (1) no-op `_require_project_access` (authentication intact)
fails `test_project_reviewer_isolated_from_sibling_hitl_work` (the
Workspace-scoped test still passes because a separate membership check
guards it — defense in depth, by design); (2) replacing `/pending`'s
authorized-scope walk with a single global store query alone does NOT leak
(the #364 per-record `authorization.permits` disclosure recheck still
filters), but with that recheck also removed both
`test_hitl_routes_are_scoped_to_the_callers_workspaces` and
`test_pending_rechecks_membership_before_disclosing_payload` fail — the
suite binds to the composition of the two layers; (3) removing only the
disclosure recheck fails
`test_pending_rechecks_membership_before_disclosing_payload`. All mutation
edits were restored byte-exact from a pre-mutation copy; `git status` and
`git diff` clean before committing this note.
