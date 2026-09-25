---
inventory-delta:
  packages/hive-conductor/backend/tests: +0 net (1 test adapted to the merged fail-closed store seam)
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
