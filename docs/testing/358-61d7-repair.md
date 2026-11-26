# Issue #358 repair — job 61d7

## Frozen scope and initial evidence

- Only issue #358 / branch `auto-358`, starting HEAD `805137e0fafb217c89c3ffbe0a874c31c550cc6c`, supplied base `8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`. Initial worktree clean.
- Process supplied dispatch snapshot and check logs only; no GitHub mutations or refreshed issue lists.
- Repair targets: actual `integration-scope` failure and requested exact vulture gate. Inspect existing audit implementation/tests and workflow gate producers before any code repair. Candidate files are the existing audit route/query/store, core audit paging, frontend audit page, associated tests/migration, and this report; change only where executed evidence warrants it.
- Driver check-3 failed: live API returned a legacy array with HTTP 200 where test expected canonical 403. Determine candidate service provenance before blaming source or changing assertions.
- Driver check-6 failed: `packages/hive-conductor/tests` has no inventory collection recipe. Other supplied lint, format, backend tests (91), and two inventory checks passed; revalidation pending.
- Prior result reported absent integration producer evidence and unavailable Docker. These claims are not accepted without current checks.

## Ambiguities / assumptions

`integration-scope: failure` supplies no failed producer details. Assume the local script plus frozen dispatch check-run evidence define the gate; do not fabricate producer success or modify the gate. No develop conflict is present, so no sync is indicated.

## Results

- Executed exact vulture gate: PASS, 1,326 findings / 1,326 reviewed identities, zero unclassified. No ledger edit warranted.
- Executed `DOCKER_HOST=unix:///var/run/docker.sock docker info`: FAIL, daemon unreachable. Do not claim Docker-backed producer validation.
- Read integration workflow and script: gate aggregates producer results, not source findings. Frozen dispatch check-runs show success on a different SHA (`bc293cd790b6`), not an identified failing candidate. UNRESOLVED after dispatch/workflow inspection; no fabricated producer verdicts and no speculative gate repair.
- Only root AGENTS.md applies. Read accepted ADR-073: preserve admin-only Sentinel decision reads and canonical authority; no competing authorization/execution path introduced.
- Candidate route `list_entries` returns `AuditPage` and `_authorized_core_audit` rejects non-admin canonical reads. The driver's legacy-array response is incompatible with this handler; do not relax the E2E assertion.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_degraded_mode_surface.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: 91 passed (18.86s), `/tmp/358-61d7-backend.log`. Million-row index migration 8.614s; first page 0.0007s; scoped page 0.0004s; max query work <2,800 VM instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: 50 passed, 4 PostgreSQL cases skipped (10.14s), `/tmp/358-61d7-core.log`. Canonical SQLite million-row load 7.840s; max VM work 3,400.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,196 files).
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`: PASS (23). This is the registered recipe, unlike driver check-6's parent path.
- `uv run python scripts/check-api-route-contracts.py`: PASS (284 handlers, 15 audited routes, zero canned).
- Ran `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classification of supplied base...HEAD>`: FAIL, six required producer results missing (docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, postgres pg17/pg18, wheel-imports). This proves locally absent evidence, not the unidentified remote failure's cause.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS (TypeScript and Vite); compilation, not browser-runtime evidence.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. `git diff --check`: PASS.

## Acceptance matrix

| Criterion | Executed evidence / remaining limits |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | 91 backend and 50 core/scope tests pass against real memory/SQLite implementations and candidate route tests. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before DB pagination | Scope/filter-before-limit and isolation tests pass; candidate canonical gate preserves ADR-073 admin-only policy. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Inspected AuditLog.tsx: 100-row pages, 500-entry retained window, visible-row slicing. Build passes; browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus loading | Filtered/scoped streaming-export tests and retention metadata tests pass; native download link inspected. Browser download UNVERIFIED. Actual retention purge is absent (`audit_query.py` explicitly assigns it to #325); retention enforcement UNVERIFIED. |
| Large-dataset query/index measurements | Both million-row SQLite tests pass with measured query VM work above; PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row tests | Existing focused memory/SQLite tests executed and passed. Four PostgreSQL cases skipped, not counted as evidence. |
| Initial-page cost independent of corpus size | SQLite VM work bounds and memory bounded-read tests pass; PostgreSQL UNVERIFIED. |
| Browser memory/DOM stays bounded | Structural implementation inspected; runtime UNVERIFIED. |

## Disposition and handoff

BLOCKED: no demonstrated candidate defect supports a speculative production,
ledger, test, or gate edit. Only this report changed; no new tests/count changes,
so no inventory-delta note is required. Preserve this checkpoint with a local
commit, without pushing or any GitHub mutation.

Required next inputs: the exact failing integration candidate SHA and producer
logs, working Docker/PostgreSQL, and a deployment of this candidate for browser
and API E2E checks. The supplied remote snapshot reports integration success on
a different head; it cannot explain the reported merge-queue failure. Do not
redispatch unchanged evidence as a guessed source repair or weaken the audit
assertions to accept an unpaginated array.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: exact-candidate producer evidence and service prerequisites}.
