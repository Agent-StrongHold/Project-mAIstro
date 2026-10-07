---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 1058 repair 6: independent re-validation of the registered-DAG recovery fix

Re-validation of the repair-lane handoff (prior job fb4e5db7 exited on worker
error without producing check logs). Performed at head 1f4c22e with no tree
edits other than this note; every result below was executed fresh in this
session, not taken from prior claims.

- The previously failing test
  `test_registered_dag_recovery.py::test_an_answered_scheduled_hitl_pause_resumes_on_the_next_tick`
  (fixed by 2e2275e1e supplying `HitlAuthorization` evidence) passes in
  isolation and with its module: 9 passed.
- Targeted HITL/workspace suites: `test_hitl_door.py`,
  `test_hitl_timeout_cancel.py`, `test_workspace_authority.py` — 39 passed.
- Full backend suite: 2660 passed / 1 skipped / 0 failed.
- `packages/maistro-core/tests/graph/durable_runs`: 472 passed / 21 skipped;
  delegation-evidence subset: 19 passed.
- `ruff check` and `ruff format --check` clean on all touched paths;
  `scripts/check-suite-inventory.py`: ok, 13 suites match recorded inventory.

Literal mutation probe (executed, then reverted byte-exact — sha256
de2882f7… verified before and after): replacing the Workspace membership
predicate inside `HitlAuthorization.permits`
(`packages/maistro-core/src/maistro/graph/durable_runs/hitl.py`) with a
mutated branch fails 13 tests in `test_hitl_door.py`, including
`test_hitl_mutation_rechecks_membership_at_the_store_boundary`,
`test_pending_rechecks_membership_before_disclosing_payload`, and
`test_hitl_routes_are_scoped_to_the_callers_workspaces` (two-Workspace
behavioral). The route-level predicate is separately guarded by
`test_hitl_membership_predicate_guards_mutation`, which stayed green under
this store-side mutation because it denies at `routes.hitl.is_member`.
