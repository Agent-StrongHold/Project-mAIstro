---
inventory-delta:
  packages/maistro-core/tests: +8
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

Validation run:

* `MAISTRO_TEST_PG_DSN=... pytest packages/maistro-core/tests/workspaces
  packages/maistro-core/tests/projects packages/maistro-core/tests/runs -q`
  -> 2218 passed, 7 skipped
* `pytest` on the maistro-server Workspace/Project/Run APIs and the Hive
  workspace/HITL/DAG scope suites -> 231 passed, 5 skipped
* `ruff check`, `ruff format --check`, `check-suite-inventory.py`
