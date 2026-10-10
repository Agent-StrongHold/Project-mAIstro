# Issue #358 repair — 964dd

## Frozen scope

- Issue #358 only; branch `auto-358`, starting head `d1265ce425ac84cdd0a7845e7f99b0174e9146d7`, supplied base `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.
- Worktree was clean. Preserve existing implementation and evidence.
- Inspect existing audit pagination backend/core/frontend, adjacent tests, ADRs, and integration-scope/vulture gates. Only evidence-backed repairs, this report, and any required inventory note are eligible for edits. No remote mutations.

## Initial evidence

- Read dispatch snapshot issue body, driver check-0 through check-7, and supplied prior result.
- Driver check-3 fails at `test_pm_workflow_api.py:271`: running service identifies `MaistroCoreBridge` but returns HTTP 200 legacy audit array for non-admin, rather than expected 403.
- Driver check-6 requests an unregistered inventory suite (`packages/hive-conductor/tests`); this is not a failed inventory comparison.
- Prior report says Docker unavailable and integration-scope producer results missing. These claims require fresh validation.
- Assumption: do not weaken audit authorization expectations to accommodate an unidentified external deployment. Determine locally whether the candidate behaves correctly.

## Checkpoint 1

- Fresh Docker check: `docker info --format '{{.ServerVersion}}'` fails to connect to `unix:///var/run/docker.sock`. No compose deployment can be validated here.
- Exact requested Vulture scan passed: 1,326 reviewed identities / 1,326 findings, zero unclassified. No ledger change warranted.
- Focused backend validation passed: **91 tests**, including real million-row SQLite index build (9.058s), initial page (0.0006s), scoped page (0.0003s), maximum query work <2,800 VM instructions. Log: job directory `worker-backend.log`.
- Read accepted ADR-073 and ADR-081226-9944. Preserve admin-only Sentinel decision access and canonical execution ownership; pagination is a read projection, not an execution authority. Retention currently reports append-only/no purge; related #325 is not silently implemented here.
- Candidate `routes/audit.py` returns `AuditPage`, never the legacy array shown by driver check-3. Canonical authorization runs before page queries. The external service is not evidence that this route implementation ran.
- Integration-scope workflow requires successful producer check runs for the exact candidate SHA. Snapshot check-run endpoint references `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not assigned head. Do not invent producer results or weaken scope.

## Checkpoint 2 — final executed validation

- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: **50 passed, 4 skipped**; job-local unique `--basetemp`, log `worker-core.log`. Canonical SQLite million-row load 8.031s; maximum measured query work 3,400 VM instructions. PostgreSQL cases skipped without a DSN.
- Backend command: `uv run pytest packages/hive-conductor/backend/tests/{test_audit_convergence,test_audit_pagination,test_audit_routes,test_degraded_mode_surface,test_noop_route_contracts}.py -x -q -s`, with separate job-local unique `--basetemp`: **91 passed**.
- `uv run ruff check .`: pass. `uv run ruff format --check .`: pass (3,196 files).
- `uv run python scripts/check-api-route-contracts.py`: pass (284 handlers, 15 audited routes, zero canned).
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`: pass (23). Correct registered suite, unlike driver's parent-directory invocation.
- `cd packages/hive-conductor/frontend && npm run build`: pass; log `worker-frontend-build.log`. This is not browser-runtime evidence.
- `uv run alembic heads`: only `062 (head)`. `uv run pytest tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_migration_chain.py -x -q` with separate job-local basetemp: **2 passed, 18 skipped** (live PostgreSQL unavailable).
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**; log `worker-integration-tests.log`.
- `git diff --check`: pass.

### Integration-scope finding (UNRESOLVED)

Inspected the captured check-run payload, not just prior reports: its
`integration-scope` conclusion is `success` for
`bc293cd790b6852da71b3e251dcecdda84bbde9b`. It does not identify the supplied
failed merge-group candidate or its failing producer. No matching failure log
was supplied. This ambiguity has been investigated twice; stop rather than
re-fetching the same scope or guessing a repair.

Measured the supplied base-to-starting-head paths with CI's classifier:
`docker_build`, `hive_e2e`, `postgres`, `wheel_imports` required; other legs false.
Executed `uv run python scripts/check-integration-scope.py --event-name merge_group
--scope-json <measured JSON>` with no fabricated producer results: **exit 1**,
missing docker-build, Hive API/UI E2E, PostgreSQL pg17/pg18, wheel-imports.
See `worker-integration-scope.log`. This demonstrates the local evidence gap,
not the root cause of the unidentified remote failure. Gate changes are not justified.

## Acceptance review

| Criterion | Evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | 91 backend and 50 core/scope tests passed; production shared query caps at 200 and orders timestamp plus row identity. |
| Authorization/scope filters before database pagination | Route denies canonical non-admin before query; bridge selects existing core audit authority; core SQL applies exact org and filters before LIMIT. Executed denial, scope-isolation and filtered-page tests. ADR-073 overrides any broader interpretation of personal canonical decision access. |
| Incremental loading and virtualization | Candidate component requests 100-row pages, retains <=500 entries and slices visible fixed-height rows. Build passed; existing browser assertions inspected. Browser runtime **UNVERIFIED**. |
| Filters/export/retention without browser corpus load | Backend filtered, scoped, capped streaming export and retention metadata tests passed. UI native download link inspected; browser download **UNVERIFIED**. Actual purge is explicitly absent, owned by related #325; do not claim retention policy enforcement. |
| Measured large-dataset query/index strategy | Both actual million-row SQLite tests passed, including VM-work bounds on production queries and deep cursor/filter shapes. PostgreSQL performance **UNVERIFIED**. |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row envelope | Executed backend/core tests cover these on SQLite/memory; four PostgreSQL cases skipped. |
| Initial-page cost independent of total corpus | Million-row query work bounded; index build measured separately. Memory tests reject corpus enumeration. PostgreSQL **UNVERIFIED**. |
| Bounded browser memory/DOM | Production cap and adjacent eight-page/<=30-mounted-row tests inspected; runtime **UNVERIFIED**. |

## Disposition

**BLOCKED**, not integration approval. Only this report changed; no new tests
or inventory delta, no production/ledger/gate edits justified by observed results.
All existing work preserved. Commit this report locally.

Required next input: exact failed integration candidate SHA and producer logs;
known deployment of this candidate for API/browser E2E; PostgreSQL/Docker access
for live query/migration validation. The driver service's legacy array cannot be
accepted as evidence of this candidate's AuditPage route. Do not relax its test.

Progress: checked 1 issue, done 0 implementation repairs, skipped 0 issues,
errors 1 unresolved integration-evidence/environment blocker; next: supply the
missing evidence/services. All acceptance limits are explicit above.
