---
inventory-delta:
  packages/maistro-core/tests: 0
---
# Issue 1150 authorization service inventory (reconciled via develop sync)

This branch previously shipped `maistro.workspaces.access`
(`AuthorizedWorkspaceProjectService`, `WorkspaceProjectAccessDenied`) as a
*service-facade* authorization seam, together with `test_authorized_service.py`
(six collected parametrized nodes over in-memory, SQLite, and configured
PostgreSQL backends). That delta (+6) applied only to the pre-develop-sync tree.

During the develop sync, #1150 was already resolved canonically on develop via
`maistro/workspaces/authorization.py` (`WorkspaceAction`,
`WorkspaceAuthorizer.require`) and `maistro/workspaces/store_boundary.py`
(`require_workspace_view` / `require_project_view` / `is_blank_principal`),
with scope enforcement moved into the stores (`principal_id` flows all the way
to `WorkspaceStore` / `ProjectScopeStore` / `RunStore`) and verified by the
`test_store_boundary_scope_conformance.py` conformance oracle
(#1809/#364, `KNOWN_GAPS = frozenset()` — green on memory, SQLite, and
PostgreSQL backends). That makes the branch's facade a **competing
authorization path**, which the campaign rules forbid.

Resolution taken here (one canonical authorization boundary, develop's):

* `git rm` `access.py` and `test_authorized_service.py` — the competing facade
  and its six-node test are superseded by develop's canonical scope-in-stores
  boundary and the conformance oracle.
* The 10 merge-conflict regions (plus `scheduler.py`) adopt develop's versions,
  so all wiring routes through `WorkspaceAuthorizer` + `require_delegable_grant`
  / `require_*_view`, never the removed facade.
* Develop's own boundary suites (`test_workspace_authorizer.py`,
  `test_store_boundary_gates.py`, `test_store_boundary_scope_conformance.py`)
  are already recorded in `docs/testing/inventory/baseline.json` on develop and
  require **no** additional delta here.

Net inventory delta for this resolution: **0** (the +6 facade test is voided by
removal; the boundary is covered by develop's baseline-counted suites). The
PostgreSQL leg of the conformance oracle is exercised via `MAISTRO_TEST_PG_DSN`
(skipped unless set, required when `MAISTRO_REQUIRE_PG_LEGS` is set), per
#1150's "green on all supported backends" criterion; the dedicated migrated
instance is taken down after the gate passes.
