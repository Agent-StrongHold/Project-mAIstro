---
inventory-delta:
  packages/hive-conductor/backend/tests: +21
---
# Audit log pagination and virtualization inventory

Issue #358 replaces the unbounded `GET /v1/audit` answer (the whole corpus, as
a bare array) with scoped keyset pagination, a bounded NDJSON export, and a
retention-bound surface, plus an incrementally loaded, virtualized UI page.

`test_audit_pagination.py` is new under `packages/hive-conductor/backend/tests`
(+21 collected node IDs): limit clamping and the maximum page size, stable
`(created_at, id)` DESC ordering with id tiebreak, continuation/empty
pages/past-the-end walks, malformed-cursor refusal, cursor stability under
deterministic between-page inserts and under threaded concurrent writes,
non-admin scope isolation (engine and route level, including cross-page
boundaries and the actor-filter probe), in-memory vs durable backend parity,
export cap/filter/scope/streaming, the retention bounds surface, and the
million-row durable performance envelope (wall-clock bounds plus EXPLAIN QUERY
PLAN evidence that the ordered walk uses `idx_audit_log_order` with no temp
B-tree sort).

`test_audit_routes.py` is updated in place, not expanded: the list-route
assertions read the new page envelope (`entries` / `next_cursor`) instead of a
bare array; test count unchanged. The e2e consumers of the same contract now
read the envelope too — `packages/hive-conductor/tests/e2e/pm-workflow.spec.ts`
(step 10, browser) and `tests/e2e/test_pm_workflow_api.py`
(`TestAuditTrail::test_audit_log_has_entries`, the `api-tests` compose service
the `hive-conductor-e2e` CI job runs; its bare-array assertion was missed by
the first pass and failed that gate). The api test also asserts the scoped
view: pmuser sees their own `login` entry, not actor-`system` rows like
`dag_create`. `tests/e2e/test_pm_agent.py` (manual script, not collected by
any suite) got the same envelope+scope treatment. Neither repair adds a
collected node ID: the api e2e drives a live compose stack and stays out of
bare collection, and the agent script is not a pytest suite.

The frontend page (`AuditLog.tsx`) is covered by the existing Playwright/e2e
and `tsc`/eslint gates; no new frontend test node IDs are added by this change.
