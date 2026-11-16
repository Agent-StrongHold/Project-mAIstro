---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue 358 repair — c978

## Frozen scope

- Assigned issue: #358 only; branch auto-358.
- Verified clean starting HEAD: fcdeb1f058873fcf6ee4f73c407d1dd71f0ee992.
- Supplied base: 35f2e0158a9138e592b56ed84bd08aa2e04c92a4.
- Inspect the existing audit query/routes, canonical persistence, audit UI and adjacent tests, relevant ADRs, integration-scope gate and exact Vulture ledger gate. No unrelated implementation edits.
- Candidate edit paths: this note; audit query/routes and their existing tests if a reproducible defect can be repaired; quality/vulture-baseline.json only for actual reviewed scanner findings.

## Initial evidence

Read supplied job check-0 through check-7 logs and prior result artifact. Driver lint/format and 76 backend tests passed. check-3 failed at test_pm_workflow_api.py:271 (expected 403, received 200 with legacy array payload). check-6 uses an unregistered suite path. These are evidence to investigate, not grounds to weaken tests or gates.

Ambiguity: integration-scope names a gate but supplies no producer outcomes. Prior result claims are not treated as verification.

## Named gate results (fresh execution)

- Exact requested Vulture command exited 1; `/tmp/358-c978-vulture.log` reports 1346 findings against 1342 trusted identities at base `91996e19223d`. Four live `get_page` methods (PgAuditLog, SqliteAuditLog, AuditLog protocol, InMemoryAuditLog) are already in the candidate ledger. Production `audit_bridge.py:186` calls this interface. No genuinely dead implementation or missing candidate row was identified. The gate explicitly requires a separately landed trusted-base grant; a candidate ledger amendment cannot authorize these identities. Do not rename live APIs to evade the scanner.
- `uv run python scripts/check-integration-scope.py --event-name pull_request` exited 1: nine required producer outcomes missing. This is missing local evidence, not proof of which remote producer failed. Inspected `.github/workflows/integration-scope.yml`: it aggregates actual same-candidate check runs. No producer artifacts/check IDs supplied; remote cause remains UNRESOLVED. No fabricated success arguments or gate weakening.
- Read accepted ADR-073, audit routes/bridge/query, canonical query helper and adjacent pagination tests. Canonical decision audit remains admin-only; legacy personal scope cannot override ADR-073. No execution/event/Goal authority changes.

## Focused validation results

Commands executed in this checkout:

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **76 passed**, 23.86s (`/tmp/358-c978-backend.log`). Real million-row SQLite index migration 11.437s; initial page 0.0011s; scoped page 0.0008s; maximum measured query VM instructions <2800.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: **45 passed, 4 skipped**, 15.67s (`/tmp/358-c978-core.log`). Canonical SQLite million-row load 11.968s; maximum measured query VM work 3400. PostgreSQL cases skipped without their DSN, so not verified.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2891 files).
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. This verifies aggregator logic, not missing producer outcomes.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests`: passed (3385 / 23 / 12811 tests). The driver's parent path `packages/hive-conductor/tests` is not a registered collection recipe. No tests were added or removed.
- Read-only `uv run python` HTTP probe of the resolved PM test target `http://localhost:8101/openapi.json`: HTTP 200; audit parameters are only action/severity/actor, response is an array, export and retention routes absent. This independently demonstrates the target lacks this candidate's API contract; exact deployed revision is unknown. No shared service was restarted or modified.

## Acceptance matrix

1. **Bounded cursor pagination, stable ordering, maximum size:** passing real route and adapter tests exercise 200-row maximum, tie-breaking, malformed cursors and continuations. Canonical routes use the bound authority, not a list-and-slice fallback.
2. **Authorization/scope before database pagination:** passing SQL adapter and route convergence tests exercise SQL scope predicates and pre-query canonical admin refusal. ADR-073 takes precedence over personal access to canonical decisions.
3. **Incremental frontend loading and virtualization:** inspected `frontend/src/pages/AuditLog.tsx` and existing Playwright audit scenarios. Requests use 100 rows, retained window 500, viewport slices DOM rows; fresh browser execution **UNVERIFIED**. Existing browser harness targets an external service and cannot establish candidate behavior at the stale default target.
4. **Filters/export/retention without browser corpus load:** backend tests pass scoped/filter-bounded NDJSON export and constant-size retention metadata. Frontend export is a direct download link, not a full-corpus JS fetch. Actual browser download **UNVERIFIED**; corpus purge is explicitly absent at `backend/services/audit_query.py:79`. #325 owns retention policy; metadata alone does not prove the full criterion.
5. **Representative large dataset/index measurements:** both real million-row SQLite envelopes ran successfully with deterministic query-work bounds above. PostgreSQL million-row envelope **UNVERIFIED** (skipped).
6. **Concurrent inserts, cursor stability, scope isolation, maximum limit, empty pages and million-row tests:** covered by the 121 passing focused tests, including acknowledged concurrent writes and duplicate request IDs; PostgreSQL variants remain skipped.
7. **Corpus-independent initial page cost:** measured durable SQLite request work passes after startup indexing. Unconditional definition of done remains unmet: `backend/services/audit_query.py:386-403` snapshots and sorts the whole in-memory corpus on every page. Canonical in-memory adapter also sorts its entries; no unconditional bounded-work claim.
8. **Bounded browser memory/DOM:** row caps inspected, but browser execution **UNVERIFIED**; arbitrary entry payload sizes are not byte-bounded by a row-count cap.

## Blocked handoff

Only this evidence note changed; no implementation repair claimed. Existing candidate ledger rows at `quality/vulture-baseline.json:1004,1013,1075,1174` already record all four retained identities. No further ledger amendment is supported by the fresh scanner findings; the missing authorization must land in the trusted base through the governance workflow. No grant, gate, authorization, scheduler or execution authority was changed.

Required next inputs: same-candidate failing producer diagnostics for integration-scope, trusted-base authorization for retained audit pagination APIs, and a candidate-built isolated service target for browser/API validation. Retention and in-memory initial-cost gaps remain acceptance blockers independently of CI evidence. Do not treat focused passes or this writer handoff as integration approval.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; blocked 1. Preserve existing implementation; no speculative or cosmetic code changes.
