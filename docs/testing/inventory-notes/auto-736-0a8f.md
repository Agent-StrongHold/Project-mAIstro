---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# auto-736-0a8f

The repair adds one route assertion that the canonical Run store admits only
one completed Run for a shipped DAG execution. The delta records that new
collected node so the Hive backend inventory gate remains additive.

# Repair round 2 (salvage of the NEEDS-REPAIR verification)

Addressed the three verifier findings on the prior state:

1. **Shipped button path.** `routes/ws.py::stream_dag_run` — the socket the
   DagBuilder Run button opens — now executes through the shared
   `routes.dags._execute_registered_dag` seam (register snapshot →
   `run_registered_dag`), streams the historical frame shape with the
   canonical Run id, and records the same `DagRunStore` projection the POST
   route records. `graph_runner.execute_dag_streaming` is no longer called by
   any DAG-run producer route (it remains a compatibility facade with its own
   direct unit tests). Reconciliation: the issue's may-modify list names only
   `routes/dags.py`, but the issue *title* — "Move the shipped DAG Run button
   onto the canonical registered-DAG execution path" — names this socket; the
   verifier confirmed the POST-only fix left the shipped button on the legacy
   path. `routes/ws.py` is DAG route code, not in the must-not-modify list,
   and the frontend file is left untouched, preserving the streaming UI
   contract (scope item 5).
2. **Owner scope.** `_resolve_run_scope_for_user` adds the missing
   no-selection step: when neither the request nor the saved DAG selects a
   Workspace, the authenticated owner's single Hive Workspace membership
   (read from `stores.workspaces`, the same seam
   `authorize_hive_dag_workspace` uses) supplies the scope instead of the
   unrelated deployment default. Zero or several memberships still fall to
   the canonical resolver, which remains the single default authority.
3. **Test gaps.** The no-query CRUD invocation, the executed (not fabricated)
   paused HITL run, and the WS button execution are now covered end to end;
   both stores are inspected for one identity in each.

No inventory-delta change in this round beyond the +4 recorded in
`736-dag-route-canonical-run.md` (this note's +1 is unchanged).

# Repair round 3 (develop rebase reconciliation)

Merged develop `ba2f1f077` (parent of this job's stated develop base
`ffd6fdb16`) into the branch. Develop had independently evolved the same
routes (#1526 "carry canonical scope through DAG execution", #766 scope
selection): `graph_runner` became a thin facade over `canonical_dag_runner`,
and both producers gained `authorize_hive_dag_scope` admission with a
`DagExecutionScope`. The conflicts were resolved by combining both sides'
guarantees rather than picking one:

1. **Request surface + admission (develop's).** `POST /v1/dags/{dag_id}/run`
   keeps the `DagRunRequest` body / query selection surface and the single
   `authorize_hive_dag_scope` admission boundary (403 on an unauthorized or
   unresolvable selection). The WS button socket keeps develop's strict
   contract: `workspace_id` is required, omission/unauthorized closes 1008
   before `accept()` — the merged DagBuilder always sends its active
   Workspace, so no shipped surface regresses.
2. **Execution seam (ours).** Both producers still execute through
   `routes.dags._execute_registered_dag` → `run_registered_dag` (register the
   saved snapshot, admit/execute exactly one canonical Run); neither calls
   `graph_runner.execute_dag`/`execute_dag_streaming`. The seam now takes the
   pre-authorized `scope` instead of re-resolving one.
3. **Scope precedence (ours, re-hosted on the canonical authority).**
   `_authorize_run_scope` replaces `_resolve_run_scope_for_user`: explicit
   request selection → the Workspace the saved DAG carries → the owner's
   single canonical Workspace membership (now read via
   `WorkspaceStore.list_for_user`, not the retired `stores.workspaces`
   projection). Unresolvable scope now fails closed with 403 instead of
   falling to the deployment-default resolver — strictly stronger than the
   issue's "no unrelated default for an authorized owner" requirement.
4. **Tests.** Develop's monkeypatch-the-facade route tests were rewritten to
   real executions against a canonical test container
   (`_canonical_container` now wires `workspace_store` sharing the Root
   Project store, so admission, authorization, and the run store share one
   scope universe): `test_run_dag_missing_scope_fails_before_execution` is
   deterministic (fresh container, zero memberships),
   `test_run_dag_carries_distinct_authorized_scopes` proves two Workspaces
   yield two completed canonical Runs with distinct Root Projects, and
   `test_activate_then_run_dag_with_a_selected_workspace_succeeds` runs the
   e2e activate-and-run step for real. Develop's
   `test_run_dag_canonical_failure_stays_failed` (fabricated
   `CanonicalDagExecutionError`) was dropped as superseded by the real
   `test_run_dag_cannot_project_a_failed_canonical_node_as_completed`
   (jira.poll e2e) — same assertions against a durable Run. Net collected
count for the suite still matches the recorded ledger (2487).

# Repair round 4 (boundary reconciliation)

Round 3's verification ruled the `routes/ws.py` diff outside #736's
may-modify collision boundary (the boundary names only `routes/dags.py`
among route files; the issue defers other producers' convergence to parent
#53). Repairs applied:

1. `routes/ws.py` and `tests/test_ws_auth.py` restored to the develop-base
   content; the socket keeps executing through
   `graph_runner.execute_dag_streaming` until #53 converges it (the removed
   round-2/3 work is preserved in branch history and in
   `../salvage-736/ws-convergence-deferred.patch`).
2. `test_ws_run_button_executes_one_canonical_run` removed from
   `test_dags_routes.py`; the WS bullet moved to the deferral section of
   `736-dag-route-canonical-run.md`, whose delta drops +4 -> +3 (this note's
   +1 is unchanged, net +4 for the branch).
3. `_execute_registered_dag`'s docstring no longer claims the socket as a
   caller; it records the missing seam explicitly.

Boundary note on the two service files that remain in the diff:

- `services/dag_run_store.py` carries projection/correlation behavior only
  (non-terminal statuses no longer stamp `finished_at`; docstrings), which
  is the boundary's stated allowance for that file.
- `services/dag_agents.py` adds one optional, default-preserving
  `node_resolver` parameter plus `get_node_resolver()`. This is the
  demonstrable route-facing gap in its already-public contract: the route's
  saved DAGs are legacy role-shaped nodes built per-node from the snapshot
  (`LegacyConductorNode`, the same construction `canonical_dag_runner`'s
  resolver and `recover_stranded_dag_runs`' `node_resolver_factory` use),
  which `run_registered_dag`'s fixed catalog resolver
  (`compose_node(kind, authorities)`) cannot construct — authorities are
  execution-wide, not per-node. Without the seam the route could not execute
  the shipped DAG shapes through the canonical path at all. Admission,
  traversal, and lifecycle remain owned by `run_registered_dag`; the seam is
  node-implementation only and defaults to the previous behavior.

The POST-route convergence, owner-scope resolution, projection correlation,
and both-stores tests from rounds 1-3 are unchanged.
