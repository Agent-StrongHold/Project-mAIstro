---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/maistro-server/tests: +8
  packages/hive-conductor/backend/tests: +3
---
# Issue 1150: Workspace/Project authorization at the store boundary

## Reconciliation with develop

Develop already owns the canonical authorization primitives:
`maistro/workspaces/authorization.py` (`WorkspaceAction`,
`WorkspaceAuthorizer.require`) and `maistro/workspaces/store_boundary.py`
(`require_workspace_view`, `require_project_view`, `is_blank_principal`).
`test_store_boundary_scope_conformance.py` is the conformance oracle for the
stores that the Workspace consumes (#1809/#364, `KNOWN_GAPS = frozenset()`).

This branch does not add a second service/facade with its own denial type.
Authorization stays in those primitives, and the previously route-local
owner/member checks move down to the stores that product consumers can reach.

## What was still unscoped (+8 inventory delta)

`get`, `update_defaults` and `transition_run` already accepted a principal,
but these by-id mutation and membership surfaces did not:

* `WorkspaceStore.delete`, `list_memberships`, `get_membership`,
  `set_membership`, `remove_membership`, and `update` (read-semantics);
* `ProjectScopeStore.create`, `delete`, `move_project`, `lineage`,
  `list_children`, `memberships_for`, `set_membership`, `merge_membership`,
  `remove_membership`, `put_resource`, `root_for_workspace`,
  `visible_resources`, and `update_defaults` (which previously authorized
  VIEW despite being an owner mutation).

A caller that reached the store directly -- `hive-conductor`'s
`services/workspace_authority.py` did -- crossed Workspace boundaries without
consulting `WorkspaceAuthorizer`. The maistro-server routes passed a route
check but then called the unscoped store, so the invariant depended on route
convention.

## Resolution

* Every method above takes an acting principal and enforces the same
  `WorkspaceAuthorizer` decision inside the memory, SQLite and PostgreSQL
  stores: VIEW for roster reads, ADMINISTER for Workspace update/delete and
  Project tree/membership mutation.
* Project membership grants additionally re-run `require_delegable_grant` for
  every action a non-owner would add, and refuse non-owner denies, so the
  store cannot be used to issue authority the route would have refused.
* Removing a membership keeps the self-service exception in the seam: a
  principal removing themselves needs VIEW; removing anyone else needs
  ADMINISTER.
* `None` is the explicit internal/system call shape (bootstrap, migration);
  a blank principal is a refusal. A missing foreign record, a foreign record
  and a blank principal produce the same denial.
* Workspace-store construction binds the paired Project store, so the
  canonical composition cannot leave the boundary unwired.
* The maistro-server Workspace/Project routes now pass the requester into the
  store calls they already authorize, Hive's `workspace_authority` passes the
  principal for set/remove/delete, and Hive's DAG admission passes the
  authenticated user into the Workspace/Project reads it used to make
  unscoped.

## Tests

`test_store_boundary_scope_conformance.py` gains four cases, collected on the
memory and SQLite legs here (+8) and on the PostgreSQL leg when
`MAISTRO_TEST_PG_DSN` is set:

* `test_workspace_membership_surfaces_are_store_scoped`
* `test_workspace_delete_is_store_scoped`
* `test_project_tree_mutations_are_store_scoped`
* `test_project_membership_surfaces_are_store_scoped`

They exercise a stranger, a plain member and an owner separately, assert the
refused mutation did not land, cover self-removal, blank-principal refusal,
member self-promotion refusal, and delegable-grant versus non-delegable/deny
refusal.

## Repair: a store refusal must not escape a route as a 500

Passing the acting principal into the store turns a previously-unscoped read
into one that can be *refused*. Two call sites treated "the store said no" as
an exception rather than as the refusal it is, so a foreign Project id became
an unhandled server fault instead of the route's own answer:

* `packages/hive-conductor/backend/services/dag_execution_scope.py`
  `authorize_hive_dag_scope` -- `project_store.get(..., principal_id=...)`
  raises `ProjectScopeDenied`, which the schedules route does not catch.
  `packages/hive-conductor/backend/tests/test_schedule_workspace_scope.py::
  test_create_refuses_a_project_outside_the_selected_workspace` failed with
  that exception (500) where the route promises 403.
* `packages/maistro-server/src/maistro_server/api/projects.py::_require_project`
  -- the same refusal escaped the Project routes, which answer an unreadable
  Project id with 404.

Both seams now translate the store's refusal into the route's own shape:
`DagWorkspaceSelectionError` (Hive -> 403) and `HTTPException(404)` (the
maistro-server Project routes). The refusal is still decided by the canonical
store; only its rendering moved back to the route.

`packages/maestro-server/tests/api/test_projects_api.py` gains one case
(+1): `test_cross_workspace_project_id_is_hidden_from_a_foreign_member` -- a
member of one Workspace asking for another Workspace's Project id gets the
same 404 an unknown id gets. It passes on `develop@e20e9f52e` and fails on
the branch before this repair, so it names the regression rather than the
implementation.

## Repair round 2: the membership-write boundary must render its refusals

The first repair covered the *read* seams. The Project membership *write*
seams had the same disease: `add_project_membership` pre-checks the
requester's delegable grants (or ownership) and then calls
`merge_membership`/`set_membership`, and `remove_project_membership`
calls `remove_membership` after its owner check -- none of the three calls
is wrapped. The store's boundary authorization re-resolves the requester's
authority inside those calls and can refuse with `ProjectScopeDenied`
(e.g. an owner's revocation committing between the route's pre-check and
the boundary check); on the branch before this repair that denial escaped
the route as an unhandled exception (a 500 in production), while the same
refusal from the pre-check rendered as 403.

`test_projects_api.py` gains three cases (+3, counted in the +4 above):

* `test_a_revocation_landing_after_the_pre_check_is_not_a_500` -- failed
  with the escaping `ProjectScopeDenied` before the fix, passes with the
  route's 403 after it.
* `test_an_ownership_loss_racing_a_membership_removal_is_not_a_500` -- the
  removal seam had the identical unguarded call at the merge base.
* `test_non_owner_cannot_delegate_a_non_delegable_action_via_regrant` --
  pins that a held-but-not-delegable action cannot be re-granted with the
  delegable flag (holding is not delegating); refused at 403 with nothing
  stored.

All three refusals are still *decided* by the canonical store; only the
rendering moved to the route, as `HTTPException(403)` with the pre-check's
own answer ("cannot delegate ..." / "Workspace owner permission required").

Validation run:

* `MAISTRO_TEST_PG_DSN=... pytest packages/maistro-core/tests/workspaces
  packages/maistro-core/tests/projects packages/maistro-core/tests/runs -q`
  -> 2218 passed, 7 skipped
* `pytest packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py`
  -> 47 passed (memory + SQLite); 68 passed with the PostgreSQL leg
  (`MAISTRO_REQUIRE_PG_LEGS=1`)
* `pytest packages/hive-conductor/backend/tests packages/maistro-server/tests`
  -> 4340 passed, 32 skipped
* `MAISTRO_TEST_PG_DSN=... pytest packages/maistro-core/tests -q`
  -> 16659 passed, 140 skipped, 7 xfailed, 7 failed. Every failure is a
  PostgreSQL conformance case in `tests/backlog/test_backlog_store_conformance.py`
  and `tests/conformance/test_approval_store_conformance.py`; the same cases
  fail unchanged on `develop@e20e9f52e` in the same container (a stale
  container schema), so they are not this change.
* `ruff check`, `ruff format --check`, `check-suite-inventory.py`
  -> ok: 21 suite(s) match the recorded inventory
* `mypy` over the AGENTS.md package list -> Success: no issues found in 906
  source files

Repair round 2 validation:

* `pytest packages/maistro-server/tests -q` -> 575 passed, 8 skipped
  (572 + the three new cases)
* `ruff check` / `ruff format --check` over the tree -> clean
* `mypy` over the AGENTS.md package list -> Success: no issues found in 906
  source files
* `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` -> exit 0 after pruning the three `bind_workspace_store`
  rows the earlier work eliminated from `quality/vulture-baseline.json`
  (617 -> 614 findings in the core-public-api-surface rule; 1326 reviewed
  identities -> 1323 findings overall)

## Repair round 3: the Workspace routes must render the boundary's refusals

Rounds 1 and 2 covered the Project *read* seams and the Project membership
*write* seams. The Workspace routes had the same disease and were left
behind: passing the acting principal into the store turned
`get`/`update`/`delete`/`list_memberships`/`set_membership`/`remove_membership`
into calls that can be *refused*, and none of the seven Workspace route
surfaces in `packages/maistro-server/src/maistro_server/api/workspaces.py`
rendered that refusal. `WorkspaceAuthorizationDenied` escaped them as an
unhandled exception (a 500 in production) instead of the answer the route
already gives for the same situation:

* a member who lost ADMINISTER between the route's own owner check and the
  boundary check got a 500 instead of the route's 403 "Workspace owner
  permission required";
* a principal who is no longer a member got a 500 instead of the route's 404
  "Workspace not found", which is also the answer that does not disclose
  Workspace existence.

Hive's Workspace routes had the same three unguarded calls
(`routes/workspaces.py`: `set_member`, `remove_member`,
`delete_canonical_workspace`), where a canonical store refusal escaped as a
500 instead of the route's 403.

Both seams now translate the store's refusal into the route's own shape:
`maistro_server.api.workspace_access.authorized` maps the refusal with the
same rule the route's own check uses (a member who lost the action -> 403; a
principal who is no longer a member -> 404), and Hive's
`routes/workspaces.py::_workspace_denial` does the same with the route's own
wording. The refusal is still *decided* by the canonical store; only its
rendering moved back to the route.

`packages/maistro-server/tests/api/test_workspaces_api.py` gains four cases
(+4, counted in the +8 above):

* `test_a_write_refusal_at_the_boundary_is_the_routes_403_not_a_500` --
  update, delete and membership write, all refused at the boundary after the
  route's owner check.
* `test_a_read_refusal_at_the_boundary_is_a_404_not_a_500` -- fetch and roster
  read after the requester's membership is revoked.
* `test_a_membership_removal_refusal_at_the_boundary_is_a_403_not_a_500` --
  the removal seam, with the membership left in place.
* `test_a_removal_refusal_after_a_membership_loss_is_a_404_not_a_500` -- the
  non-disclosing answer for a principal who is no longer a member.

`packages/hive-conductor/backend/tests/test_workspaces.py` gains three cases
(+3): the membership write, the membership removal and the Workspace delete,
each refused by the canonical store after the route's own owner check.

All seven cases fail on the branch before this repair (the refusal escapes as
an unhandled `WorkspaceAuthorizationDenied`) and pass with it.

Repair round 3 validation:

* `pytest packages/maistro-server/tests/api/test_workspaces_api.py -q` ->
  20 passed (16 + the four new cases)
* `pytest packages/hive-conductor/backend/tests/test_workspaces.py -q` ->
  71 passed (68 + the three new cases)
* `pytest packages/maistro-server/tests -q` -> 579 passed, 8 skipped
* `pytest packages/hive-conductor/backend/tests -q` -> 3771 passed, 24 skipped
* `pytest packages/maistro-core/tests -q` -> 15654 passed, 1131 skipped,
  7 xfailed
* `ruff check` / `ruff format --check` over the tree -> clean
* `mypy` over the AGENTS.md package list -> Success: no issues found in 906
  source files
* `check-suite-inventory.py --show --compact` -> 21 suites match the recorded
  inventory: core 16792, maistro-server 587, hive-conductor backend 3795,
  total 32404
* `MAISTRO_TEST_PG_DSN=... MAISTRO_REQUIRE_PG_LEGS=1 pytest
  packages/maistro-core/tests/workspaces -q` -> 342 passed, 2 skipped -- the
  store-boundary conformance cases collected on the memory, SQLite *and*
  PostgreSQL legs, so the two-principal/two-Workspace refusal is proven on
  every supported backend
* `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` -> exit 0 (1326 reviewed identities -> 1323 findings,
  0 unclassified, 0 never-allowlist)
