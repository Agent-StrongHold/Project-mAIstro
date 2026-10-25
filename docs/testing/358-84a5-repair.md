# Issue #358 repair checkpoint — 84a5

## Frozen scope

- Assigned issue: #358 only; linked PR #1712 is evidence, not an integration target.
- Worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `3c43800d50caac6ae15cacc0f84bdbf44b6005d2`; supplied base `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`. Working tree initially clean.
- Review scope: existing issue diff (audit routes/query/stores, core pagination, migration, AuditLog UI and adjacent tests), integration-scope gate and vulture gate. Changes limited to evidence-backed repairs in those files, any required inventory note/retained-identity ledger amendment, and this report.
- No remote list refresh, GitHub mutation, or unrelated repair.

## Initial evidence

- Driver check-3.log fails against a service returning a bare legacy array where candidate E2E expects canonical denial based on health. Must distinguish stale service from candidate regression; do not weaken assertion.
- Driver check-6.log requests `packages/hive-conductor/tests`, which has no suite inventory recipe.
- Prior result reports missing integration-scope producer results and unavailable Docker. These claims require fresh local checks.
- Ambiguity: dispatch supplies only `integration-scope: failure`, without its log. Proceed by examining workflow/script and invoking with verified local refs; do not invent producer success.

## Validation and outcome

### Checkpoint 1

- Exact requested Vulture scan passed: 1,326 reviewed identities / 1,326 findings, zero unclassified (`worker-vulture.log`). No speculative ledger edit warranted.
- Fresh `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'` failed: cannot connect to Docker daemon. Neither `postgres` nor `initdb` is on PATH; no test PostgreSQL DSN configured.
- Read repository instructions and accepted ADR-073: canonical decision audit remains admin-only. Candidate list route returns `AuditPage` and authorizes before query, unlike the bare array returned by the driver's external service.
- Integration-scope workflow consumes successful check runs for the exact candidate SHA. Local test success cannot substitute for missing producer checks.
- Frontend read confirms incremental 100-row requests, 500-row retained window, fixed-height virtualization and native download link. Runtime validation pending; do not treat inspection as proof.

### Checkpoint 2

- Backend: `uv run pytest packages/hive-conductor/backend/tests/{test_audit_convergence,test_audit_pagination,test_audit_routes,test_degraded_mode_surface,test_noop_route_contracts}.py -x -q -s` (unique job-local basetemp): **91 passed**. Million-row SQLite index build 10.497s; first page 0.0007s, scoped page 0.0004s; maximum query work <2,800 VM instructions. Log: `worker-backend.log`.
- Core/scope: `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` (separate job-local basetemp): **50 passed, 4 skipped**. Canonical SQLite million-row load 8.982s; maximum query work 3,400 VM instructions. PostgreSQL cases skipped without DSN. Log: `worker-core.log`.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**, log `worker-integration-tests.log`.
- `uv run ruff check .`: pass. `uv run ruff format --check .`: pass (3,196 files).
- `uv run python scripts/check-api-route-contracts.py`: pass (284 handlers, 15 audited routes, zero canned).
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`: pass (23). This is the registered suite; the driver's parent path is invalid.
- `cd packages/hive-conductor/frontend && npm run build`: pass, log `worker-frontend-build.log`. Build is not browser runtime validation.
- Read accepted ADR-081226-9944 and the audit bridge/shared SQL: paging remains a read projection of the existing audit authority, with no competing execution authority.

### Integration evidence ambiguity — UNRESOLVED

Inspected the supplied snapshot once: its check-run endpoint is for
`bc293cd790b6852da71b3e251dcecdda84bbde9b`; integration-scope concluded **success**.
That is neither the assigned HEAD nor an identified failed merge-group candidate.
Workflow inspection confirms it requires exact-candidate producer results. The
failure named in dispatch cannot be diagnosed from a success on another SHA.
Stop investigating this ambiguity rather than re-fetching scope or guessing a fix.

Executed `uv run python scripts/check-integration-scope.py --event-name merge_group
--scope-json <classifier output>` on the frozen source paths (remaining documentation
paths only require the already-required Docker leg). **Exit 1**: no exact-candidate
results for docker-build, Hive API/UI E2E, PostgreSQL pg17/pg18, wheel-imports.
Log: `worker-integration-scope.log`. No fabricated `--result` arguments were supplied.
This proves missing local integration evidence, not the cause of the unidentified
remote failure. No gate or ledger amendment is justified.

## Acceptance evidence

| Criterion | Executed evidence / remaining limit |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | 91 backend + 50 core/scope tests passed against candidate modules; shared production query clamps at 200 and uses timestamp plus row identity. |
| Authorization/scope filters before database pagination | Passing route denial/scope tests and adapter tests exercise canonical admin gate and SQL org/filter predicates before LIMIT. ADR-073 governs canonical decisions; legacy personal scope is only the unbound fallback. |
| Incremental loading and virtualization | Production component inspected and build passed. Browser runtime **UNVERIFIED** without a known candidate deployment. |
| Filters, export, retention without browser corpus load | Filtered/scoped/capped streaming export and retention metadata backend tests passed. Native browser download **UNVERIFIED**. Actual retention purge is explicitly absent and belongs to related #325; no claim of purge enforcement. |
| Measured query/index strategy on representative large datasets | Both actual million-row SQLite checks passed with work bounds and timings above. PostgreSQL strategy **UNVERIFIED** (no DSN/service). |
| Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages, million-row envelope | Executed backend/core cases pass on SQLite/memory; four PostgreSQL cases skipped. |
| Initial page bounded independently of corpus size | Million-row production-query work bounds passed; memory tests reject corpus enumeration. PostgreSQL **UNVERIFIED**. |
| Browser memory/DOM row count bounded | Inspected 500-entry retained window and visible-row slicing; build passed, but browser-runtime bound **UNVERIFIED**. |

## Disposition and handoff

**BLOCKED**. This round changes only `docs/testing/358-84a5-repair.md`; no test
additions or inventory delta, no production changes supported by the observed
failures. Preserve the candidate and its strict E2E authorization assertion.
Driver check-3's bare legacy array is inconsistent with this candidate's paged
route, and cannot demonstrate execution of this candidate.

Required next inputs: the exact failed merge-group SHA and producer logs;
a known deployment of this candidate for API/browser E2E; working Docker and
PostgreSQL for live integration/query/migration validation. Do not rerun the
same repair dispatch as though missing producer evidence were a code defect.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 unresolved
integration evidence/environment blocker. Next: provide those inputs. Report
committed locally; no GitHub mutations or unrelated changes.
