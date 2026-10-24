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

## Develop sync reconciliation (base `4de7e906d9`)

The next develop sync arrived as a preserved in-flight merge of the older
snapshot `e20e9f52e` plus a fresh merge of `origin/develop` (`4de7e906d9`,
59 commits past it). Both resolved in place: merge `148944a03` kept the
branch's `_fresh_store` reload-before-inspection helper in
`services/dag_run_inspection.py` (the merged snapshot had made no change to
that region), and merge `153757ca7` unioned the `dag_run_store` import
(branch's `DagRunStore` binding beside develop's `MAX_EVENTS_PER_RUN` for the
bounded canonical events page).

The sync brought develop's new `tests/test_goal_inspection.py` (#2181), whose
projection double patched `get_dag_run_store` with a `SimpleNamespace`
carrying only `get_run` — written against develop's direct-store contract.
The M1-E refresh contract
(`test_history_inspection_refreshes_before_http_reads`, marked
`M1-E/history-replica-refresh`) requires every production inspection to
reload the shared projection first, so the double gained a `reload=lambda:
None` seam: a reload that finds nothing and a `get_run` that answers None is
exactly the "projection unavailable" state the test models. No test was
added, removed, or renamed — no inventory delta; the suite total stays
3983 (3957 passed + 26 skipped locally at the merged head).

## Supply-chain CI repair (no inventory delta)

The merge-queue evaluation of `e44f03a4` failed the pip-audit and frontend
audit gates on locked dependency advisories, not on this issue's diff. Both
fixed versions existed, so per the gate's own rule no allowlist entry was
added: `uv.lock` moved fastmcp 4.0.11 → 4.1.3 (GHSA-7xgj-8392-5q4r,
GHSA-vqqp-x5qm-5qp4), setuptools 84.0.0 → 84.2.1 (GHSA-xmj3-9gf7-h52w), and
`packages/maistro-canvas/frontend/package-lock.json` took `npm audit fix` for
undici/zod (3 HIGH). No test was added, removed, or renamed — the suite total
stays 3983; the branch's own suites were re-run green at the repaired head
(root `tests/` 5638 passed, hive-conductor backend 3957 passed + 26 skipped,
canvas 79 passed, `pip-audit` gate OK, `npm audit --audit-level=high` OK).
