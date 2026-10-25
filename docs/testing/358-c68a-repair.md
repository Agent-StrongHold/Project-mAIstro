# Issue #358 repair — c68a5072

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `66a8a71cbddfe10ffbd846e98bb00a221d1047b6`; supplied base `b1f17b8d6246d347f617fb2c0b969e6798e0152b`.
- Only issue #358 / linked PR #1712 evidence in the supplied dispatch snapshot; no remote enumeration or mutations.
- Files under review: existing audit route/query/bridge/stores, core audit pagination/stores, AuditLog UI, adjacent audit tests and migration tests, existing PM API tests implicated by check-3, integration-scope workflow/checker, vulture checker, and this report. Edits limited to evidence-backed issue repairs and required inventory notes.
- Initial working tree clean; no incoming edits to salvage.

## Supplied evidence inspected

- Current check-0/1/2: dependency sync, lint, format passed (not treated as fresh verification).
- check-3: live E2E `TestDAGLifecycle.test_06_list_dag_runs` received HTTP 500; 1 failed, 6 passed, 6 skipped.
- check-4: 78 passed; check-5/7 inventories passed.
- check-6: unsupported inventory recipe `packages/hive-conductor/tests`.
- Prior result eff09620 reports the same validation command failure, not an audit implementation diagnosis.

## Ambiguities / assumptions

- `integration-scope: failure` has no diagnostic inline. Inspect supplied snapshot and local workflow before choosing a repair; do not weaken gates or guess scanner identities.
- A live service failure may be environmental or unrelated. Do not modify canonical DAG execution merely to hide it.

## Progress

- Exact requested Vulture gate freshly passed: 1328 reviewed identities / 1328 findings, trusted base 9bd1a93eefc4. No ledger amendment is justified.
- Integration-scope workflow requires nine specialized producer outcomes; it is an aggregator, not an application test. Initial parser missed nested snapshot data (discard that diagnostic). Correct recursive parsing found all nine same-starting-head producers succeeded: docker-build 112632565051, durable-events 112632564848, hive-conductor-e2e 112632564892, hive-conductor-e2e-ui 112632564908, object storage (MinIO) 112632564942, postgres (pg17) 112632565077, postgres (pg18) 112632564983, strike-ladder 112632565004, wheel-imports 112632564897. Executing `uv run python scripts/check-integration-scope.py --event-name pull_request` with those nine captured `--result NAME=success` values PASSED. This verifies supplied evidence only, not future-head CI.
- Production legacy in-memory query explicitly sorts the corpus per page; durable path uses indexed bounded seeks. Retention explicitly reports `corpus_purge: none` and delegates policy to #325. Do not claim these limitations are repaired by pagination.
- Read ADR-073: bound canonical decision audit must remain admin-only; actor scoping on the legacy fallback is not permission to open canonical records. No execution or authorization authority changes planned.
- Fresh core pagination + workspace scope command: `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: 50 passed, 4 PostgreSQL skips (DSN unset), 9.84s. Million-row canonical SQLite load 7.769s, maximum 3400 VM instructions. Core memory path DOES have bounded seek indexes (legacy JsonStore fallback does not).
- Fresh isolated reproduction of `uv run pytest packages/hive-conductor/tests/e2e/test_pm_workflow_api.py::TestDAGLifecycle::test_06_list_dag_runs -x -q` FAILED at line 198: HTTP 500 from default localhost:8101. This reaches a live service, not an in-process branch build.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps ...` failed: cannot connect to Docker daemon. Do not assume environment availability from dispatch claims.
- Missing paths `tests/e2e/conftest.py` and `tests/playwright.config.ts` were not found; skipped. Actual E2E config resolved as `tests/e2e/playwright.config.ts`.
- Live target provenance: port 8101 is owned by a rootless container proxy; uvicorn runs from `/app/backend`, not this worktree. `/health` reports start 2026-10-03T12:27:09Z, version 0.9.0, MaistroCoreBridge/MaistroServerTaskBackend, configured LLM, not CI's no-key StubAgentPort harness. Exact image revision/log provenance UNRESOLVED after two inspections. No service restart or authority changes made; branch code cannot be indicted solely by this live failure.
- `uv run ruff check .` and `uv run ruff format --check .`: PASS (3137 files).
- `uv run pytest tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_revision_metadata.py tests/migrations/test_single_migration_head.py -x -q`: 7 passed. `uv run alembic heads`: single `061 (head)`.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests`: PASS, 3466 / 14918 cases, no duplicate evidence. The driver's unsupported `packages/hive-conductor/tests` recipe remains a driver configuration problem, not something to repair by changing inventory policy.
- `git diff --check`: PASS. Only this report is changed; no new tests and thus no inventory delta.

## Acceptance accounting at the frozen head

| Criterion | Executed evidence / remaining limitation |
| --- | --- |
| Backend bounded cursor, stable ordering, maximum size | 78 backend + 50 core/scope tests passed. Reviewed reachable `list_entries -> page_core_audit_entries -> AuditLog.get_page` and legacy `page_entries` paths. Queries cap at 200 plus lookahead; row identity breaks timestamp ties. |
| Authorization/scope before database pagination | Route authorization and adapter tests passed. ADR-073 denies non-admin canonical reads before I/O. Core SQL starts with exact org predicate; legacy SQL applies principal aliases and filters within bounded index seeks, not post-filtering. |
| Frontend incremental loading and virtualization | Source has cursor continuation, fixed-height row window, 500-entry cap, stale-generation checks; existing `pm-workflow.spec.ts` cases cover these. Branch-built browser execution **UNVERIFIED** this round. Captured UI-producer success is not case-level proof. |
| Filters/export/retention without whole corpus in browser | Executed backend tests prove filtered/scoped paged NDJSON export, cap and retention metadata. Frontend uses native download rather than a full-response JS blob (source review only). Operational retention **NOT IMPLEMENTED**: `audit_query.py:79` explicitly reports `corpus_purge: none`. #325 owns policy; no competing purge authority introduced here. Browser download behavior **UNVERIFIED**. |
| Query/index strategy measured on representative large data | Fresh real million-row SQLite tests: legacy <2800 VM instructions, canonical 3400; first/scoped legacy pages 0.0006/0.0004s. PostgreSQL million-row test **UNVERIFIED** locally (DSN unset; Docker endpoint unavailable). Migration metadata/index tests passed, one Alembic head. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | All corresponding backend and SQLite/memory adapter tests executed successfully. Four PostgreSQL cases skipped, not counted as acceptance. |
| Initial page cost independent of corpus size | Proven by deterministic work budgets for durable SQLite and bounded read-count tests for canonical memory. Unconditional definition of done **NOT MET** by reachable legacy memory fallback: `audit_query.py:402-403` copies/sorts all entries per page. Startup index creation also intentionally scales with corpus. |
| Browser memory/DOM bounded | Source caps retained rows at 500 and mounts a visible slice; existing Playwright bounded-window test is meaningful but **UNVERIFIED** locally against this branch. |

## Decision and next action

**BLOCKED**, not merge-ready. This round found no reproducible failure in the two named CI gates at the supplied starting head: exact Vulture passes and integration-scope accepts the nine captured successful producers. Amending a matching ledger, modifying gate policy, or inventing another code repair would not address actual evidence.

The live driver failure is reproducible, but its target is a long-running configured container outside the assigned worktree and not the CI no-key harness. Its exact source revision and exception remain UNRESOLVED. Preserve the failing assertion and canonical Workspace/Run authorization; do not turn the 500 into an accepted result or open a second authorization path. Next driver action: provision a fresh branch-built service on a dedicated endpoint, rerun the PM API and audit Playwright cases, and collect its traceback if the 500 persists. Provide an isolated PostgreSQL DSN for the four skipped cases. Do not reuse or mutate the running deployment to make validation green.

Separate issue-owner reconciliation remains required for operational retention (#325) and the unconditional initial-page bound on the legacy memory fallback. Those are explicit acceptance gaps, not repaired by passing lint or inventories.

Changed file: `docs/testing/358-c68a-repair.md` only (evidence/handoff). No production/test/gate/ledger changes, no new authority, no remote mutations. This report is committed locally as required; no code repair is claimed.

Snapshot outcome: checked 1, done 0, skipped 0, errors 1 (live validation failure; acceptance incomplete). Next: branch-provenance validation harness and unresolved acceptance gaps above.
- Fresh focused backend command: `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` PASSED (78 tests, 19.12s). Million-row legacy SQLite index setup 8.723s; initial/scoped pages 0.0006/0.0004s; maximum query work <2800 VM instructions.
