# Issue #358 repair — fdc92

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `ad94161795caf437ba8305142e4cdffde6723905`; supplied base `626683154ce9dbd521e6754cee494190c0fb29f0`.
- Only issue #358: audit pagination implementation, adjacent tests, relevant ADRs, integration-scope gate, explicitly permitted vulture ledger repair if evidenced, and this report. No other issue/PR processing or remote mutations.
- Starting worktree clean; no uncommitted salvage required.

## Initial evidence

Read frozen dispatch issue body and driver check-0 through check-7 logs. Driver lint/format and 78 focused backend tests passed. check-3 failed at `test_pm_workflow_api.py:198`: live `/v1/dag-runs` returned 500. check-6 passed an unregistered inventory suite (`packages/hive-conductor/tests`). Prior result reports missing same-candidate integration producer evidence and legacy in-memory page cost; neither claim is assumed verified.

Ambiguity: integration-scope failure has no inline log in assignment. Inspect the repository gate and frozen dispatch evidence, without re-fetching GitHub. Existing unrelated branch changes are preserved, not treated as assigned implementation scope.

## Gate inspection checkpoint

- Exact requested Vulture gate executed successfully: 1,336 findings, 1,336 reviewed identities, zero unclassified/never-allowlist findings. No ledger amendment is justified.
- `integration-scope.yml` checks same-candidate specialized producer results. The supplied check logs do not include these results. No change to gate logic or invented success inputs is justified.
- Current legacy memory query explicitly snapshots and sorts the entire store on every request (`audit_query.py:_sorted_ascending`); the prior defect remains in source. Validate reachability and reproduce structurally before disposition.

## Independent validation checkpoint

- Read repository instructions and accepted ADR-073, ADR-081226-69ee, ADR-081226-7248. Canonical audit stays admin-only; legacy actor-scoped reads do not widen canonical authority. No execution or event authority changes are appropriate.
- Frozen dispatch contains one integration-scope result: success for `84081fba82fc9a0aa386af6a8cc1b093b0997de2`, not this candidate. After two inspections, missing candidate failure details are **UNRESOLVED**; no further enumeration or fetching.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`: exit 1, nine required producers missing. This is a missing-evidence check, not a claimed reproduction of the remote producer failure.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. Gate remains unchanged.
- Focused Hive audit/convergence/noop pytest: 78 passed (109.84s). Million-row legacy SQLite index migration 98.813s (startup work); first page 0.0006s, scoped page 0.0004s, maximum measured query work <2,800 VM instructions. Deterministic query bounds pass despite slow fixture construction.
- Production reachability inspected: `routes/audit.py:list_entries` calls the legacy memory query when the engine lacks a bound core audit and persistence is absent. This is an explicit supported route, not merely a unit-test adapter.
- Focused core audit/pages/scope pytest: 76 passed, 5 skipped (9.49s). Canonical SQLite million-row load 7.552s, max query work 3,400 VM instructions. PostgreSQL runtime remains UNVERIFIED: no test DSN, and `DOCKER_HOST=unix:///var/run/docker.sock docker info` cannot connect.
- Independent structural probe with the real `JsonStore` and `page_entries(limit=1)`, wrapping `_created_at_of`: corpus 100 -> 100 visits; corpus 10,000 -> 10,000 visits; each returns one row. Initial-page cost criterion FAILS for the legacy memory route. Fixing this safely requires tracking all supported mutations rather than a length-based stale cache; not a speculative CI-gate repair.
- Attempted browser config path `packages/hive-conductor/playwright.config.ts`: not found; skipped. Resolve actual configuration before any browser command. Actual configs resolved under `frontend/` and `tests/e2e/`; default e2e target is localhost:8101, not a candidate-owned server. Do not count prior browser claims as fresh evidence.
- Audit migration tests: 2 passed. Suite inventory passes for the registered suites: Hive backend 3,456; core 13,944; Hive API e2e 23. Driver check-6 used the wrong suite path; the correct registered path is `packages/hive-conductor/tests/e2e`. No inventory recipe/gate change is needed.
- `uv run ruff check .`, `uv run ruff format --check .` (3,006 files), and `git diff --check`: PASS.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS (TypeScript checks and production Vite bundle). This is not a browser runtime test. Generated artifacts remain ignored/uncommitted.

## Acceptance disposition

| Criterion | Fresh evidence and limitations |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | 78 Hive and 76 core tests passed, including limit clamping, timestamp ties, concurrent inserts and cursor continuity. |
| Authorization/scope before database pagination | HTTP scope/convergence tests and SQLite filter-shape tests passed. Accepted ADR-073 keeps canonical decision audit admin-only. PostgreSQL runtime UNVERIFIED (skipped, unavailable daemon). |
| Incremental frontend loading and virtualization | Production component inspected (`AuditLog.tsx`), TypeScript/build passed. Existing browser test source inspected; browser runtime UNVERIFIED this round, not inferred from prior reports. |
| Filters, export, retention without browser-wide corpus | Backend filter, capped streaming export, retention metadata tests passed. Frontend links download directly, but browser runtime UNVERIFIED. Actual corpus purge is absent (`audit_query.py:79`), explicitly delegated to #325; not claimed complete here. |
| Representative large-dataset query/index measurement | Both million-row SQLite tests executed: legacy <2,800 VM instructions, canonical max 3,400. PostgreSQL million-row runtime UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row coverage | Focused Hive/core suites execute all these cases; SQLite and canonical memory coverage passed. |
| Initial page cost independent of corpus | FAIL: reachable legacy memory fallback visits 100/10,000 rows for a one-row page. Durable and canonical memory tests pass; they do not excuse this path. |
| Browser memory/DOM row count bounded | Source retains 500 entries and renders a window; fresh browser/heap proof UNVERIFIED. Build alone does not prove this criterion. |

## Exact validation commands

All validation used long tool timeouts (1,000s; initial Vulture 600s).

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-integration-scope.py --event-name pull_request
node --test tests/ci/integration-scope.test.cjs
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/persistence/test_sqlite_audit.py packages/maistro-core/tests/persistence/test_pg_audit.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s
uv run pytest tests/migrations/test_audit_cursor_indexes.py -x -q
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e
DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'
uv run ruff check .
uv run ruff format --check .
npm --prefix packages/hive-conductor/frontend run build
git diff --check
```

The one-off `uv run python` structural probe used real JsonStore writes at corpus
sizes 100 and 10,000, patched `_created_at_of` with `wraps` (no return-value
substitution), called `page_entries(limit=1)`, and asserted one returned row and
exactly corpus-size timestamp visits. This is diagnostic evidence, not a newly
added repository test identity.

## Handoff

**BLOCKED.** Changed only `docs/testing/358-fdc92-repair.md`; no production,
test, gate, grant, or ledger edits. No test inventory delta is needed because
no tests were added or removed. Preserve the existing branch implementation.

The exact requested Vulture gate already passes at the assigned starting HEAD.
The named integration failure cannot be repaired from a success result for a
different SHA. Required next evidence: the failed producer/check log and exact
candidate SHA (or all same-candidate successful specialized results). Do not
substitute the old PR result, weaken the gate, or mark it green locally using
invented `--result` arguments. No unresolved merge state exists locally.

Separate acceptance work remains: a mutation-aware bounded legacy memory query,
fresh candidate browser validation, reachable PostgreSQL validation, and an
explicit retention-purge scope decision with #325. A heuristic cache would risk
stale/scope-incorrect audit reads and is not an appropriate guessed gate repair.
The driver live DAG-list HTTP 500 remains unresolved; this round made no changes
to the unrelated DAG lifecycle or its live deployment.

Progress: {checked: 1, done: 0, skipped: 0, errors: 2, next: exact-candidate integration evidence and legacy memory page-cost repair}.





