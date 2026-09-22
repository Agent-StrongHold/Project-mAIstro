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
