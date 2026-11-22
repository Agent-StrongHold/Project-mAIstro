# Issue #358 repair checkpoint (700a)

## Frozen scope

- Issue #358 only; branch `auto-358`, starting HEAD `190e06d990ebefd160b25628c1bacb7c00a48ce3`, supplied base `82097f6b7acca58ffc27a934b305faaee7a37915`.
- Inspect existing audit pagination implementation, adjacent tests, ADRs, supplied dispatch evidence and check logs. Repair only demonstrated integration-scope / exact-debt-ledger failures. No GitHub mutations or develop sync unless an actual conflict is established.
- Candidate changes: this report; audit implementation/tests and inventory note only if a regression is reproduced; vulture ledger only for actual reported retained identities.
- Starting tree clean. All supplied check logs inspected: lint/format pass; backend audit checks 91 pass; inventory backend/core pass. Package-wide tests hit a live service returning a legacy list instead of the expected canonical denial. `check-6.log` requests an unregistered inventory suite.

## Ambiguity / assumption

`integration-scope` failure has no detailed command in the brief. Inspect workflow and supplied PR check evidence once for its exact invocation. Do not infer scanner identities or weaken tests. The live service may not be the assigned checkout; establish provenance before attempting any repair.

## Validation

- Exact requested vulture command PASS: 1,326 findings / 1,326 reviewed identities, zero unclassified. No ledger amendment is justified.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info` FAIL: daemon unreachable. Docker-backed producer validation cannot be claimed.
- Read root repository instructions (only AGENTS.md found) and accepted ADR-073; canonical Sentinel decision reads remain admin-only, not personal legacy audit reads.
- Integration ambiguity inspected in frozen dispatch and local gate: supplied check-run evidence is for `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not the starting candidate. Gate requires specialized producer verdicts; missing producer logs are not source defects. UNRESOLVED; do not keep searching or invent verdicts.
- Focused candidate backend tests: **91 passed**, including real million-row SQLite query execution. Index migration 8.415s; first page 0.0026s, scoped page 0.0003s; maximum query VM instructions <2,800 (`/tmp/358-700a-backend.log`).
- Focused core audit/scope tests: **50 passed, 4 skipped** (PostgreSQL unavailable). Canonical SQLite million-row load 7.484s; maximum VM work 3,400 (`/tmp/358-700a-core.log`).
- `uv run ruff check .` and `uv run ruff format --check .`: PASS (3,196 files).
- `uv run python scripts/check-api-route-contracts.py`: PASS (284 handlers, 15 audited routes, zero canned).
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/tests/e2e`: PASS (23). This registered recipe is the correct replacement for the driver's unsupported parent-suite invocation; no repository gate change required.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. This tests aggregator behavior, not candidate producer success.
- Inspected reachable audit routes and adjacent tests: list/export share `_authorized_core_audit`, canonical non-admin reads fail before I/O. Fallback scopes are passed into the paging query. A legacy array cannot be returned by the candidate list handler.
- UI has 100-row incremental pages, a 500-entry retained window, and visible-row slicing. Browser runtime remains UNVERIFIED. Retention reports `corpus_purge: none`; enforcement is explicitly deferred to #325, not implemented here.
- Independently fetched live `/openapi.json` using the E2E target (`HIVE_BASE_URL`, default localhost:8101): HTTP 200, audit response schema is an **array** and parameters are only `action`, `severity`, `actor`. Candidate `routes/audit.py:110` exposes `limit`, `cursor` and an `AuditPage` response. This establishes a foreign/stale contract, not candidate deployment provenance; do not modify assertions to accept it.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`: FAIL closed without scope/results, listing nine absent specialized producers. This is a local evidence availability check, **not** reproduction or diagnosis of the unknown remote producer failure. No fabricated `--result ...=success` supplied.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS (TypeScript + Vite). This does not substitute for browser tests.
- `git diff --check`: PASS.

## Executed focused test commands

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_degraded_mode_surface.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

## Acceptance matrix

| Criterion | Evidence / limits |
| --- | --- |
| Bounded cursor pagination, stable ordering, max page size | Existing candidate route/memory/SQLite tests pass (91 backend, 50 core/scope). PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Scope-before-limit and canonical admin-only tests pass; ADR-073 governs canonical decision reads. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Source inspected and frontend build passed; browser behavior UNVERIFIED. |
| Filters, export, retention without loading browser corpus | Existing filter/scoped streaming-export and retention metadata tests pass. Browser download and retention purge UNVERIFIED; purge absent and assigned to #325. |
| Measured representative large datasets | Two real million-row SQLite tests passed with deterministic VM work bounds and measurements above. PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope tests | Focused memory/SQLite tests executed successfully; four PostgreSQL tests skipped, not acceptance evidence. |
| Bounded initial-page cost | Memory bounded-read and SQLite VM-work tests pass. PostgreSQL UNVERIFIED. |
| Bounded browser memory/DOM | 500-entry retained window and visible-row slice inspected; runtime UNVERIFIED. |

## Disposition / next inputs

**BLOCKED**, not integration approval. Only this report changed; no tests added or counts changed, so no inventory-delta note needed. No ledger edit: exact gate already passes. No demonstrated source regression warrants a speculative production repair, gate change, or relaxed assertion. No merge conflict exists in this worktree.

Required next: exact failing integration candidate SHA and producer logs, working Docker/PostgreSQL, and a deployment of this candidate for API/browser E2E. Do not repeat this repair lane with the same foreign live service and absent producer evidence.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: candidate deployment and missing integration producer evidence}.

