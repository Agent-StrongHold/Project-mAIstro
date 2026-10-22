# Issue #358 repair checkpoint (b518)

## Frozen scope

- Issue #358 only; supplied PR #1712 snapshot, head `d03cfe77e2f5f1103964739c5a656be0d9cc2978`, base `d99e598e1084a183d1280fbe9a2c4de8b50b7f2b`.
- Candidate audit route/query/bridge, core audit stores/cursors, AuditLog frontend, adjacent audit/e2e/migration tests, relevant ADRs/workflows, and this evidence note. Vulture ledger changes only if the required scan identifies reviewed retained debt.
- Clean incoming worktree; no incoming edits to salvage. No GitHub mutations or ref refresh needed.
- Supplied check-3 fails at `test_pm_workflow_api.py:271`: external service returns 200 legacy array instead of expected canonical 403. This is evidence of a service/candidate mismatch, not yet evidence of a candidate regression.
- Supplied check-6 uses an unregistered suite (`packages/hive-conductor/tests`); do not alter inventory gates to accommodate it.
- Ambiguity: integration-scope failure lacks a direct command in the brief. Inspect the captured check and local workflow once, then replay the documented gate against frozen evidence. Do not guess remote status.

## Executed results

- `uv sync --locked --extra dev`: passed.
- Required exact vulture scan: passed, 1,323 reviewed identities / 1,323 findings; zero unclassified or never-allowlist identities. No ledger amendment justified.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: daemon unavailable. PostgreSQL/container-backed acceptance remains unverified unless another configured service is available.
- First extraction of captured checks assumed object data but found a list; local extraction only failed (AttributeError), no candidate change.

- Focused candidate backend audit suite: **91 passed in 18.34s** (`repair-backend.log` in the job directory). Includes real auth/routes, canonical/legacy convergence, filters/export/retention, ties/concurrency/max/empty pages and million-row SQLite queries. Legacy million-row index migration 8.427s; first page 0.0006s, scoped page 0.0003s; query VM work <2,800.
- Frozen checks select required Docker, PostgreSQL, Hive E2E, and wheel-import legs. `docker-build` is still `in_progress` in the supplied snapshot; the other required legs report success. Initial local replay incorrectly passed unrelated check names and was rejected by the gate. Corrected replay below will use only specialized check names, without fabricating results.
- Accepted ADR-068/073 preserve canonical admin-only decision audit before I/O; legacy actor scopes remain SQL constraints. No authorization or execution authority changes are justified.

- Corrected `uv run python scripts/check-integration-scope.py --event-name pull_request --scope-json <classifier output> --result <captured specialized results>`: **exit 1**, exclusively `docker-build: required but result was in_progress`. See `repair-integration-corrected.log`. This resolves the invocation ambiguity but cannot resolve missing completed evidence. No workflow change justified; remote evidence is frozen, not refreshed.
- Core audit/scope tests: **50 passed, 4 skipped in 9.81s** (`repair-core.log`). Canonical SQLite million-row load 7.629s; maximum VM work 3,400. All PostgreSQL audit cases skip without `MAISTRO_TEST_PG_DSN`.
- Migration cursor-index/chain tests: **2 passed, 18 skipped**. Database migration execution remains unverified.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed (3,208 files).
- `npm --prefix packages/hive-conductor/frontend run build`: passed TypeScript/Vite (`repair-frontend-build.log`). This is not browser-runtime evidence.

- Inventory gates passed: backend **3,599** and core **15,820** collected identities, no duplicates. Commands: `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests` and the same with `--suite packages/maistro-core/tests`. Driver check-6 is an invalid suite selection, not missing test inventory.
- Read-only `GET http://localhost:8101/openapi.json` independently confirms the external audit response schema is `type: array`, whereas this candidate's `routes/audit.py:118` returns `AuditPage`. The failing driver assertion is not testing the candidate's bounded-page contract. Do not weaken it to accept the old service.
- `git diff --check`: passed. Only this evidence note changed; no tests added, removed, or recounted, so no inventory delta is needed. No ledger edits, gate changes, background services, or remote mutations.

## Exact focused test commands

```text
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_degraded_mode_surface.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s
uv run pytest tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_migration_chain.py -x -q
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

## Acceptance reconciliation

| Criterion | Executed evidence / residual gap |
| --- | --- |
| Bounded stable cursor pagination and maximum page | Candidate route and store tests pass for SQLite/memory, including tie-breaking by row identity, concurrent inserts, clamping, empty and malformed pages. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Candidate real auth/convergence tests prohibit any store read before the canonical admin gate; SQLite/core scope tests prove query-time scope and filters. `audit_pages.page_query` binds org/user filters before LIMIT. ADR-073's admin-only canonical authority supersedes any interpretation allowing personal reads of canonical decisions. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Production routed component uses cursor loading, generation guards, a 500-entry retained window and viewport slicing. Build passes. Existing Playwright cases inspect late responses, continuously visible sentinel, and <=30 mounted rows; browser execution UNVERIFIED this round. |
| Filters/export/retention without browser corpus loading | Backend query/filter/streamed-export-cap/retention tests pass. UI uses native download, not a buffered Blob. Native browser download execution UNVERIFIED. Retention honestly reports `corpus_purge=none`; actual corpus purge remains separate issue #325, not implemented or claimed here. |
| Representative large-dataset query/index strategy | Both actual million-row SQLite benchmarks pass deterministic query-work bounds (legacy <2,800 VM instructions; canonical 3,400). PostgreSQL million-row EXPLAIN/BUFFERS test UNVERIFIED (skipped). |
| Tests: concurrent inserts/cursor stability/scope/max/empty/million rows | Focused 91 backend + 50 core tests pass against real candidate stores/routes; PostgreSQL variants UNVERIFIED. |
| Initial page cost independent of corpus | Indexed memory read-budget tests and real SQLite million-row query work bounds pass. Startup index-build cost is recorded separately. PostgreSQL runtime UNVERIFIED. |
| Browser memory/DOM bounded | 500-entry cap and viewport slicing inspected, frontend compiles; browser execution UNVERIFIED. Source inspection alone is insufficient for this definition of done. |

## Disposition

**BLOCKED.** No evidence-supported production repair or vulture amendment was identified. The named integration gate cannot be proven from incomplete frozen Docker evidence; the external API is not the candidate; Docker is unavailable for PostgreSQL/container acceptance. Captured unrelated `test`, lint/type, and Quality failures lack diagnostic logs and are not attributed to this issue or speculatively repaired.

Handoff requirements: completed required specialized CI evidence and diagnostic logs for actual failing jobs; a working Docker endpoint or test PostgreSQL DSN; a candidate HTTP/UI service for the existing audit browser tests. Preserve current assertions and gates. No new items started.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: "completed integration evidence and candidate PostgreSQL/browser validation"}.

This note is the only changed file and is committed locally as the required writer checkpoint; it is not integration approval.
