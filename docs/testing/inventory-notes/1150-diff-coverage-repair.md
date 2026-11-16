---
inventory-delta:
  packages/maistro-core/tests: +10
  packages/hive-conductor/backend/tests: +1
---
# Issue 1150 CI-repair: cover the boundary's own refusal branches

The diff-coverage gate (`scripts/check-diff-coverage.py`, lines 90% / branches
80%) failed on the branch's head because the *changed* boundary lines it
touches were not exercised by any test, not because the behavior was wrong.
Reproduced locally at the develop merge base `ac1e2f9556f178fe2597927021d6218d78663101`
with the three coverage producers (`packages/maistro-core/src/maistro`,
`packages/maistro-server/src/maistro_server`,
`packages/hive-conductor/backend`):

```
packages/hive-conductor/backend/routes/workspaces.py: 50.0% of 2 changed branch arcs (need 80%); partial at 70
packages/maistro-core/src/maistro/projects/authorization.py: 80.0% of 20 changed lines (need 90%); uncovered 125, 133, 150, 151
packages/maistro-core/src/maistro/workspaces/store_boundary.py: 81.1% of 53 changed lines (need 90%); uncovered 102, 131, 133, 154, 156, 187, 207, 208, 215, 216
```

(The PostgreSQL producers cover `projects/pg_scope_store.py` and
`workspaces/pg_store.py`; those files are backend legs, so the three above are
the genuine shared-code gaps.)

Each uncovered line is a documented contract the stores cannot reach on their
own because a store always passes a principal it resolved:

* `store_boundary.py` 102 / 133 / 156: a **blank** principal is a refusal in
  `authorize_membership_removal`, `require_workspace_action_on` and
  `require_membership_removal_on` (the internal `None` shape is 131 / 154).
* `store_boundary.py` 187: the same blank-principal refusal in
  `require_project_administer`, which collapses to `ProjectScopeDenied`.
* `store_boundary.py` 207-208 / 215-216: `require_project_administer_on` is
  the Project twin of the workspace in-transaction re-check; its deny path
  catches `WorkspaceAuthorizationDenied` and re-raises the pre-write
  `ProjectScopeDenied`.
* `projects/authorization.py` 125 / 133 / 150-151: `authorize_membership_write`
  treats `None` as internal, refuses a blank principal, and translates a
  member's `PermissionError` (they hold no delegable grant) into
  `ProjectScopeDenied`.
* `routes/workspaces.py` 70: `_workspace_denial` renders a refusal that carries
  no membership as the non-disclosing **404**; only the with-membership 403
  branch was exercised.

## Tests (+10 core, +1 hive)

`packages/maistro-core/tests/workspaces/test_store_boundary_gates.py` gains
seven cases (+7): the blank-principal refusal in `authorize_membership_removal`,
`require_workspace_action_on` and `require_membership_removal_on`; the
`None`-as-internal return of the two re-check helpers; the blank-principal
refusal in `require_project_administer`; and
`require_project_administer_on` refusing a plain member on the writing
connection with the same `ProjectScopeDenied` the pre-write check raises.

`packages/maistro-core/tests/projects/test_authorization_membership_write.py`
is new (+3): `None` returns before the store is consulted, a blank principal is
a refusal, and a member who cannot delegate the action is refused.

`packages/hive-conductor/backend/tests/test_workspaces.py` gains one case (+1):
the store's refusal from a principal who is no longer a member (roster replaced
so `admin` is off it, the route's own checks let through) renders as the route's
404, not a 500 and not the 403 a member who lost the action gets.

All eleven assert the behavior they name; none pins a coverage number. The
PostgreSQL producers are unchanged, so the two Project stores' backend legs keep
their existing coverage and the gate has no new unmeasured file.
