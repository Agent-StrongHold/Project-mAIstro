---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
---
# issue-337-durable-dag-state

The tests add the missing parity and authorization evidence for the
node-metrics projection and the feedback correlation path:

- a writer, an already-running replica refreshed from shared rows, and a fresh
  post-restart store read the same observation;
- replaying one canonical Attempt replaces rather than duplicates its metric;
- the bounded projection evicts its oldest row from both memory and durable
  records;
- production history inspection refreshes the shared projection before HTTP
  reads, closing the already-running replica freshness gap without changing
  the accepted direct-store/SSE cache contract;
- workspace-scoped reads are fail-closed: a foreign observation is
  indistinguishable from a missing one, and an observation that names no
  Workspace is served to no HTTP reader;
- feedback refuses a missing or foreign run (404), a projection-only run
  without canonical identity (409), and an unknown node (404);
- per-node feedback correlates to the canonical NodeRun and its latest
  Attempt, never a borrowed projection id.

DAG history, feedback outcomes, and user profiles already had focused parity
suites on this base. The implementation keeps their accepted ADR boundaries:
DAG SSE subscribers remain process-local, and canonical execution identities
are required for every accepted feedback write — the projection-free
compatibility path is retired rather than kept as silently uncorrelated
feedback.

## Develop sync reconciliation (base `fad17a87c`)

The develop sync conflict in `routes/dag_run_inspection.py`, `routes/feedback.py`,
`routes/metrics.py` and `tests/test_feedback_route.py` resolved in place — HEAD's
projection fixtures and `_seed_visible_run` seam kept beside develop's
`require_actor_id`, canonical-identity requirements and
`_resolve_project_id`/`_resolve_org_id` reads — and the merge commit is
`8f3173fa5`.

The merge brought develop's cutover retirement ledger
(`quality/workspace-retirement.json`, #1046) in next to #337's `node_metrics`
store, which had been declared in `stores.py` before that ledger existed. The
gate failed in the ledger's own documented shape: every `stores.py` store is a
census row, and a retiring surface may not gain consumers, so a new store there
is born unable to name a reader (`scripts/check-workspace-retirement.py`, and
the same rule in `stores.register_json_store`'s docstring). The store therefore
moved out of `stores.py` into `services/node_metrics_store`, declared beside
the only code that writes it and adopted through
`stores.register_json_store`, which keeps the persistence wiring and
initialization centralized. No ledger row was added or edited. The durability
contract is unchanged: `foundation._init_state` still configures the
registered store, and it still shares the state database for restart and
replica reads. `test_the_projection_store_is_registered_not_declared_in_stores_py`
pins the ownership invariant.
