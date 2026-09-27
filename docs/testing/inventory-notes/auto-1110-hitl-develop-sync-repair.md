---
inventory-delta:
  packages/hive-conductor/backend/tests: +0

Net suite delta is zero: one test was adapted in place (see below) and no test
was added or removed.
---

# auto-1110 HITL develop sync repair (#1110)

Resolves the preserved develop sync conflict on `auto-1110` (merge of
`55c5ad892` "WIP: M1-B8 — Represent HITL as waiting human NodeRuns (#1327)")
and repairs the two real incompatibilities the merge surfaced, both proven by
run failures rather than scanner output.

## Merge conflict resolution

`packages/hive-conductor/backend/tests/test_hitl_timeout_cancel.py` kept both
sides' fixtures: the branch's `reviewer_client` (used by
`test_expiry_endpoint_only_settles_authorized_workspace_projects`) and
develop's `seeded` fixture that binds the legacy store to the route through an
explicit `get_canonical_run_store` test seam.

## Route repair: fail-closed spine resolution

develop's `test_hitl_endpoint_fails_closed_without_canonical_spine` failed on
the merged tree: `list_pending_human_work` derived the authorized Workspace set
first and returned `[]` (200) for a principal with no Workspaces, never
reaching `_store()`. A degraded canonical spine must be an unavailable
capability (503), not a silent empty queue, so the spine handle is now resolved
before any authorization-derived early return. Resolving the handle touches no
data; disclosure remains bounded by Workspace membership and Project authority,
and unscoped principals are still 403'd by the privilege middleware.

## Test repair: reviewer-isolation expiry test binds the explicit seam

`test_expiry_endpoint_only_settles_authorized_workspace_projects` seeded the
legacy document-shaped store and relied on the route resolving
`get_run_store()`; the merged fail-closed `_store()` (correctly) refused it and
returned 503. The test now binds the same explicit `get_canonical_run_store`
seam the other legacy-store tests use.

## Mutation experiment (acceptance evidence)

Temporarily replacing `authorize_project` in `_require_project_access` with a
no-op — authentication untouched — makes
`test_project_reviewer_isolated_from_sibling_hitl_work` fail (a denied Project
answer settles with 200) while middleware-scope tests still pass. The scope
checks are load-bearing. The expiry scope test stays green under the same
mutation because `authorized_project_ids` plus store-level membership
revalidation cover that path independently (defense in depth).

## Re-validation at the 2026-09 develop sync (this round)

The front-matter delta line above previously carried prose after the count,
which `check-suite-inventory.py` cannot parse (`cannot read ... as
'<suite>: <±count>'`); the count is bare and the prose lives in this body.
`origin/develop` (b906cc577, username allocation + manual-fire admission) was
merged with no conflicts. Re-run at merge commit ffe46913:

- `check-suite-inventory.py`: 13 suites match the recorded inventory
  (hive-conductor backend: 2767 collected; the `+0` delta holds).
- `test_hitl_door.py` + `test_hitl_timeout_cancel.py`: 33 passed; workspace
  authority + privilege middleware: 12 passed; full backend suite: 2761
  passed, 6 skipped; `packages/maistro-core/tests/runs`: 876 passed,
  209 skipped.
- The mutation experiment above was re-executed in this round: the isolation
  test failed under the no-op mutation and passed again after revert.
- `ruff check .` / `ruff format --check .`: clean; vulture baseline: 1414
  reviewed identities, 0 unbanked.
