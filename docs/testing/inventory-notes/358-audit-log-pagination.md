---
inventory-delta:
  packages/hive-conductor/backend/tests: +21
  packages/hive-conductor/tests/e2e: +0
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

## Repair validation (2026-10-01)

Scope: issue #358 only, starting at f86865626; retained prior work intact.
Read AGENTS.md, both CLAUDE.md files, ADR-019, ADR-062, and ADR-068.
No execution, event, or authorization authority changes. Retention purge remains
owned by #325: `/retention` reports constants, not an implemented purge policy.

Added three Playwright cases to the existing `pm-workflow.spec.ts` (the pytest
inventory therefore changes by +0): late first-page and continuation responses
after a filter change, plus an eight-page scroll walk verifying cursor requests,
the 500-entry retained window, at most 30 mounted rows, and refresh. The two
race cases failed against the starting production component: a late first page
replaced the filtered result; a late continuation appended an old-filter row.
`AuditLog.tsx` now invalidates abandoned walks on filter change, refresh, and
unmount, including errors and load-lock completion. Export keeps current filters.

### Executed validation

- `DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p auto358-repair
  -f packages/hive-conductor/docker-compose.test.yml
  -f /tmp/auto-358-validation/compose.yml up --build --abort-on-container-exit
  --exit-code-from e2e-tests e2e-tests`: 109 passed (3.3m), including the three
  new cases. The temporary override only resets published ports to avoid the
  existing deployment on :8101. Same API command with `api-tests`:
  10 passed, 13 pre-existing DAG/workspace-dependent skips.
- Before the fix, the new browser cases ran against the starting component:
  2 failed (stale first page and continuation), 1 passed (bounded window).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q`:
  40 passed in 19.56s when run serially. Under concurrent build load the
  million-row test failed at line 526: first page 5.205s exceeds 5.0s.
  That failure is retained as evidence, not dismissed by the successful rerun.
- `uv run ruff check .` and `uv run ruff format --check .`: pass.
- `npm run lint` / `npm run build` in `frontend/`: pass, 95 lint warnings,
  zero errors; both TypeScript configurations and Vite production build pass.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e`:
  pass, 3,045 and 23 pytest node IDs. The driver's `--suite
  packages/hive-conductor/tests` is not a supported recipe.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: pass, 1,383 reviewed
  identities, zero unbanked. No ledger amendment is warranted.
- `uv run python scripts/check-integration-scope.py --event-name pull_request
  --result hive-conductor-e2e=success --result hive-conductor-e2e-ui=success`:
  fails closed for missing docker-build, durable-events, MinIO, pg17, pg18,
  strike-ladder and wheel-imports evidence. This is not a claim those jobs
  failed. The single starting-head CI snapshot had the API check successful
  but integration-scope still pending; the supplied failure lacks a producer
  log. No gates were weakened or GitHub state mutated.

Logs for this repair are under `/tmp/auto-358-validation/` in the worker
runtime (`api-e2e.log`, `audit-ui-before.log`, `ui-e2e-after.log`,
`audit-backend-serial.log`, `query-cost.log`, `integration-scope.log`).
The supplied check-3.log targets a foreign deployment (user `dude`, not the
harness's `pmuser`); fresh Compose validation above does not touch it.

### Acceptance evidence and unresolved work

- Bounded pages, stable cursors, limit clamp, empty pages, concurrent memory
  writes and SQL scope-before-limit: covered by the executed backend tests.
  Durable parity is tested; threaded concurrent durable insertion is not.
- Incremental loading and DOM window: real Chromium ran eight 100-row pages;
  at most 30 mounted rows, retained count capped at 500, refresh restores the
  first row. Generation guards prevent cross-filter response contamination.
  This is not a byte-level heap profile or a million-page browser soak.
- Export: backend scope/filter/cap tests pass; the browser uses an attachment
  link instead of buffering a Blob. Filter-specific export URL is asserted.
- Retention: only read-surface constants are exposed. Actual purge policy is
  UNVERIFIED/not implemented here, explicitly deferred to #325.
- **Initial query cost is not bounded independently of corpus size.** A fresh
  million-row `State`/`PersistedStore` fixture, seeded with the test's
  `_perf_row`, measured the exact production `_page_sql` via SQLite's progress
  handler (1,000 VM instructions per callback): first warm page 101 rows,
  <1,000 steps, 0.0007s; absent actor scope zero rows, 6,000,000 steps, 2.0379s;
  deep cursor 100 rows, 7,000,000 steps, 0.2409s. All plans say
  `idx_audit_log_order (store_name=?)`, not an actor/cursor seek. Cold index
  creation took 3.6726s. An indexed ORDER BY/no temporary sort does **not**
  prove bounded scanning. Required follow-up: scope/filter-aware seek strategy,
  migration before serving requests, and deterministic work-count regressions.
- Integration-scope aggregate: UNVERIFIED for the complete required set.

Handoff verdict: NEEDS-REPAIR, not integration approval. The focused frontend
repair is complete; #358's broader performance/retention acceptance remains
open. No scheduler, Goal store, event authority, or authorization path changed.
