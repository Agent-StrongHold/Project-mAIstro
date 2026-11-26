# #358 repair handoff — e6fda

## Frozen scope and outcome

- Assigned `auto-358`, clean starting HEAD
  `bc0265b69eda1ab7e58d442cc41efcc40e6a05f2`, supplied base
  `66f3cea9e98980f146a12cf3142d66e30986d276`; both resolved locally.
- Inspected only #358 audit production paths, adjacent tests, accepted ADR-073
  and ADR-081226-9944, supplied evidence, integration-scope and vulture gates.
- **BLOCKED:** no production defect reproduced; no speculative source, ledger,
  authorization, test-expectation, or gate changes. This report is the only
  tracked change. No tests added, so no inventory delta is required.
- Audit pagination remains a read projection, not another execution/event
  authority. ADR-073's canonical admin-only decision audit takes precedence
  over legacy personal-trail behavior. The execution spine is unchanged.

## Executed evidence (not inherited verification claims)

Logs are under `/home/dev/maistro/jobs/e6fda996950a427f96d1ae54e100eb3c/`.

| Command / selection | Result |
| --- | --- |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 3,168 files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1,328 reviewed identities, zero unclassified; no ledger amendment justified |
| `uv run pytest packages/hive-conductor/backend/tests/{test_audit_convergence,test_audit_pagination,test_audit_routes,test_degraded_mode_surface,test_noop_route_contracts}.py -x -q -s` | 91 passed; `worker-backend.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_migration_chain.py -x -q -s` | 52 passed, 22 skipped without live DB environments; `worker-core.log` |
| `uv run alembic upgrade head`, then `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s` against isolated PG18 | Migration through 061 passed; 16 passed, zero skips; `worker-pg-{migrate,tests}-final.log` |
| `npm run build` in `packages/hive-conductor/frontend` | Passed; `worker-build.log` |
| `uv run pytest packages/hive-conductor/tests/e2e/test_pm_agent.py packages/hive-conductor/tests/e2e/test_pm_workflow_api.py -x -q` against candidate-owned servers | Each mode: 10 passed, 14 skipped; `worker-stub-api-final.log`, `worker-canonical-api-corrected.log` |
| Frontend's `playwright test --config packages/hive-conductor/tests/e2e/playwright.config.ts pm-workflow.spec.ts --grep audit --retries=0` | Each mode: six passed; `worker-stub-browser-final.log`, `worker-canonical-browser-corrected.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e` | Passed: registered suite has 23 tests |
| `uv run python scripts/check-api-route-contracts.py` | Passed: 284 handlers, 15 audited routes, zero canned |
| `node --test tests/ci/integration-scope.test.cjs` | 12 passed |
| `uv run pytest tests/test_check_integration_scope.py -x -q` | 18 passed |
| `git diff --check` | Passed |

The HTTP supervisor used this checkout's `uvicorn main:app`, ephemeral
loopback ports, fresh Conductor data/vault/identity/state paths, and explicit
`HIVE_BASE_URL`. Both `StubAgentPort` and `MaistroCoreBridge` were independently
asserted from health before testing. Canonical mode used the repository's
absolute `MAISTRO_AGENTS_DIR` and a dummy local router key, not a live LLM.
Local HTTP explicitly set `SESSION_COOKIE_SECURE=false` and
`ALLOW_INSECURE_TRANSPORT=true`; production defaults remain secure.
`NODE_PATH` pointed to the installed frontend `node_modules`.
PG18 used a fresh UTF8 cluster and the same isolated DSN for `DATABASE_URL`
and `MAISTRO_TEST_PG_DSN`. Supervisors stopped all child servers before returning.
No shared service/database was stopped or modified.

Initial supervisor failures are not hidden: omitted insecure-development
cookie settings caused admin 401; missing `NODE_PATH` prevented Playwright
collection; a relative agents directory degraded the bridge. PG startup first
used unavailable psycopg2, then SQL_ASCII caused SQLAlchemy's bytes/string
version error. Corrected invocation settings above passed without source edits.

## Acceptance mapping

- **Bounded cursor pagination, stable ordering, maximum size:** focused backend
  and all three canonical adapter tests pass, including timestamp ties,
  duplicate request IDs, floor/ceiling limits, empty and malformed cursors.
- **Scope before database pagination:** real SQLite/PG adapter isolation tests,
  backend deny-before-query tests, and live HTTP/browser checks in both modes
  pass. Canonical non-admin list/export is 403; legacy reads stay actor-scoped.
- **Incremental loading and virtualization:** routed browser tests pass with
  eight pages, late-response rejection, visible-sentinel continuation,
  at most 500 retained entries and 30 mounted rows, and refresh recovery.
- **Filters/export/retention without browser corpus loading:** native filtered
  NDJSON downloads complete against both production modes, with no fetch/XHR
  or Blob download; server cap/laziness and retention constants are tested.
  Corpus purge is explicitly absent and remains #325, not claimed here.
- **Representative million-row measurement / bounded initial-page cost:**
  legacy SQLite query work <2,800 VM instructions; canonical SQLite maximum
  3,400; migrated PostgreSQL maximum 54 query blocks across first/deep pages
  and filter shapes. Index construction is startup/migration work, not hidden
  request work. Production memory tests prohibit corpus enumeration.
- **Concurrent inserts, cursor stability, scope isolation, limits and empty
  pages:** the backend/core selections above exercise these explicitly;
  live PG pagination has no skipped cases.
- **Browser memory/DOM bound:** bounded retained-record and mounted-row tests
  pass. No heap-byte profiling claim; unrelated full LLM flows remain skipped.

## Unresolved integration evidence / actionable handoff

`uv run python scripts/check-integration-scope.py --event-name pull_request`
exited 1: all nine required producer conclusions were missing. This command
without `--result` arguments demonstrates absent local evidence, **not** the
cause of the reported remote merge-queue failure. The supplied check-runs are
for `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not the assigned candidate;
their integration-scope result is success. No failing exact-candidate producer
log was supplied. Gate logic must not be changed or supplied synthetic success.

1. Provide the failed merge-group SHA and its integration-scope log plus
   required producer logs/results: pg17, pg18, MinIO, durable-events,
   strike-ladder, Hive API/UI E2E, wheel-imports and docker-build.
2. Driver `check-3.log` targets a service returning a legacy JSON array from
   export while reporting a canonical bridge. That cannot implement this
   checkout's NDJSON/403 route. Point `HIVE_BASE_URL` at the candidate-owned
   deployment. Both unchanged candidate-mode tests passed locally.
3. Driver `check-6.log` uses unregistered parent suite
   `packages/hive-conductor/tests`; use `packages/hive-conductor/tests/e2e`.

Progress: checked 1 issue; done 1 validation handoff; skipped 0 issues;
1 unresolved integration-evidence blocker. No push, GitHub mutation, merge,
grant/ledger edit, discarded work, or integration approval.
