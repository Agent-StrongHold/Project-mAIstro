---
inventory-delta:
  packages/maistro-core/tests: +8
  packages/maistro-server/tests: +1
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
