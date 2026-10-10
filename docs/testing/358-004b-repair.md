# Issue #358 repair — job 004b

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `a1313d2b68ec3491d491dab547f4cf6b67689fc8`; supplied base `675db8be6c41b020ffffb224b2748c159c78a122`.
- One item: #358. No GitHub mutations or ref refreshes.
- Files considered for repair: existing audit route/query/bridge and persistence implementations, AuditLog frontend, adjacent audit tests and inventory notes, integration-scope workflow/checker (inspection only), and this report. Vulture ledger only if the required scan identifies reviewed retained debt.
- Starting tree clean; no incoming changes to salvage.

## Evidence and assumptions

Read supplied dispatch issue body, driver check-0 through check-7 logs and prior result. Driver lint/format and 91 backend tests pass. Driver check-3 fails against a running HTTP server: audit response is an unpaginated list and returns 200 where the test expects 403. This is evidence of a live-server mismatch, not yet evidence of a defect in this checkout. Driver check-6 requests an unsupported inventory suite. Prior integration-scope failure and Docker unavailability will be independently checked.

Assumption: this is a writer repair round; do not alter authorization expectations or gate policy to make an incompatible external service pass. No new tests yet; inventory unchanged.

Fresh first checkpoint: exact requested vulture scan passes (1,323 reviewed identities / 1,323 findings, zero unclassified); no ledger amendment is justified. `DOCKER_HOST=unix:///var/run/docker.sock docker ps` fails: cannot connect to daemon. Integration-scope workflow is an aggregator requiring successful specialized producers for the candidate SHA; it is not itself a failing application test. Read route: canonical audit authorization is admin-only before paging; unbound legacy reads alone allow own-actor scope. Retention endpoint explicitly declares purge belongs to #325. No code changes justified by evidence so far.

Second checkpoint: read accepted ADR-068 authorization ordering, ADR-073 admin-only decision audit, ADR-081226-69ee canonical graph execution model; no competing authorities introduced. Focused backend audit/convergence/degraded/noop suites: **91 passed** (18.58s). Core audit-pages and store-boundary scope suites: **50 passed, 4 PostgreSQL skips** (9.53s). Logs: job directory `worker-backend.log`, `worker-core.log`. Legacy million-row SQLite index migration 8.377s, first page 0.0007s, scoped page 0.0004s, max work <2,800 VM instructions. Canonical million-row SQLite load 7.550s, max query work 3,400 VM instructions. These prove tested memory/SQLite boundaries, not PostgreSQL or live browser behavior.

## Final validation and gate diagnosis

All commands ran in the assigned worktree with 600–900 second validation timeouts.

| Command | Fresh result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,323/1,323 identities |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_degraded_mode_surface.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` | 91 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` | 50 passed, 4 skipped (PostgreSQL DSN absent) |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,223 files |
| `uv run python scripts/check-api-route-contracts.py` | PASS, 284 handlers, 15 audited routes |
| `node --test tests/ci/integration-scope.test.cjs` | 12 passed |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` | PASS, 3,599 |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 15,880 |
| `npm --prefix packages/hive-conductor/frontend run build` | PASS, TypeScript and Vite |
| `DOCKER_HOST=unix:///var/run/docker.sock docker ps` | FAIL, daemon unavailable |

Used validated supplied base in `git diff --no-renames --name-only <base>...HEAD`, then passed measured paths to `uv run python scripts/ci_merge_group_scope.py --json`. Required scope: docker_build, hive_e2e, postgres, wheel_imports. Executed `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <measured-json>` without invented producer conclusions: exit 1, missing docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, postgres (pg17), postgres (pg18), wheel-imports. This demonstrates absent evidence, not the cause of the reported remote failure.

Independently inspected supplied frozen check-run data, selecting highest ID per check name: integration-scope and all six producers succeeded on `af2538ff1b5b0ac74489f60a5add139cae064faf`, not the assigned candidate. Exact failing candidate producer logs remain **UNRESOLVED**. No remote refresh and no gate changes.

Fresh read-only GET `http://localhost:8101/openapi.json` reports `/v1/audit` parameters only action/severity/actor and array response. Candidate `backend/routes/audit.py` instead declares limit/cursor and AuditPage. Therefore driver check-3's failure at `test_pm_workflow_api.py:271` cannot validate this checkout: the external API's deployed commit is UNVERIFIED. No test expectations relaxed and no unrelated server changed. Driver check-6 uses an unregistered inventory suite; valid registered suites above pass.

## Acceptance accounting

| Criterion | Executed evidence / remaining limits |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page | Passing backend/core tests exercise real route and memory/SQLite adapters, ties, cursor decoding, clamping and final/empty pages. |
| Authorization/scope before DB pagination | Passing canonical admin-before-query tests and SQL legacy own-actor scope/filter tests; accepted ADR-073 requires admin-only canonical decision audit. PostgreSQL execution UNVERIFIED. |
| Incremental frontend loading and virtualization | Production build passes; inspected cursor continuation and viewport slicing. Browser runtime UNVERIFIED. |
| Filters/export/retention without whole-corpus browser loading | Backend filtered/scoped/capped streaming export and retention metadata tests pass. Native download inspected; browser download behavior UNVERIFIED. Operational purge is not implemented (`audit_query.py` reports `corpus_purge: none`); #325 owns purge, so full retention acceptance needs explicit reconciliation. |
| Query/index strategy measured for large datasets | Real million-row SQLite measurements recorded above; PostgreSQL million-row execution UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row tests | 141 focused tests pass; 4 PostgreSQL tests skipped. |
| Initial page cost independent of total log size | Passing indexed-memory read-budget tests and million-row SQL VM instruction budgets. Startup index creation is separately corpus-sized work. |
| Bounded browser memory/DOM rows | Source caps retained entries at 500 and mounts a viewport window; runtime DOM/heap bound UNVERIFIED. |

## Disposition and next action

**BLOCKED**. Changed file: this report only. No new tests or inventory-count changes; no inventory delta needed. No production, authorization, scheduler, ledger, grant or gate edits warranted by actual evidence. Preserve Goal → Graph → Run → NodeRun → Attempt and canonical audit authority.

Required next inputs: exact failed candidate producer conclusions/logs, and an isolated candidate-built API/UI plus PostgreSQL environment. Do not repeat repair dispatches against port 8101's incompatible contract or substitute another SHA's successes. Run candidate live API/native-download/browser-window tests and PostgreSQL envelope when those prerequisites exist; reconcile operational retention acceptance with #325.

Progress: checked 1, done 0 acceptance-complete, skipped 0 issues, errors 1 unresolved integration/environment blocker; next: provision exact-candidate validation environment and supply producer failure evidence. Report committed locally; no GitHub actions.
