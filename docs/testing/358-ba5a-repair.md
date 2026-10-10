# Issue #358 repair checkpoint (ba5a)

## Frozen scope

One item: issue #358, branch auto-358, starting HEAD
`e9d039c26d6680206372ff4d86a0b852a4af2da2`, assigned base
`56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
Working tree was clean. No GitHub mutations or ref synchronization requested by
an evidenced conflict. Scope: existing audit pagination implementation, adjacent
tests, integration-scope and exact-debt-ledger validation, and this report.
Potential repair files: backend/services/audit_query.py, backend/tests/test_audit_pagination.py,
and quality/vulture-baseline.json only if the actual scan requires amendment;
inventory notes accompany any test additions. Other implementation files are
read-only acceptance evidence for this round.

## Initial evidence / assumptions

Supplied check-1/2 passed lint/format; check-4 passed 77 backend tests.
check-3 failed external PM audit access (expected 403, received 200).
check-6 uses an unregistered inventory suite (`packages/hive-conductor/tests`).
These are observations, not proof of current local behavior. Previous result
reports integration-scope lacks candidate producer results and Vulture lacks
trusted-base authorization. Re-run both, without weakening gates or fabricating
producer results. No merge conflict exists; do not assume a develop sync is needed.
Full issue acceptance criteria extracted from the frozen dispatch JSON. No
additional issue/PR enumeration will be performed.

## Gate checkpoint

Fresh exact Vulture command exits 1 and names the same four `get_page`
identities. Integration-scope exits 1 without candidate producer conclusions;
its Node tests pass. Logs: `repair-vulture.log`, `repair-integration.log`,
`repair-integration-tests.log` in the assigned job directory. No source defect
has been identified in either gate. Legacy memory reads explicitly sort the
whole corpus; this is an existing substantive acceptance gap, not a gate fix.

## Focused validation checkpoint

Fresh Ruff check and format check PASS. Backend: 77 passed in 19.43s.
Core: 45 passed, four PostgreSQL cases skipped in 9.82s. Million-row legacy
SQLite migration 9.321s; initial page 0.0007s; scoped page 0.0004s; maximum
VM work <2,800. Canonical SQLite million-row load 7.806s, maximum VM work
3,400. Registered inventory suites pass: backend 3,396; core 13,780;
Conductor E2E 23. Frontend production build PASS. Docker socket is unavailable,
so PostgreSQL runtime remains UNVERIFIED. Command logs are `repair-{ruff,format,
backend,core,inventory,build,docker}.log` in the assigned job directory.

Accepted ADR-068 and ADR-073 require canonical decision audit to remain
admin-scoped. Routes call `_authorized_core_audit` before querying; personal
actor scope applies only to the unbound legacy fallback. Do not weaken the
external E2E's 403 assertion to accommodate a different service contract.
Accepted ADR-081226-69ee retains Graph/Run/NodeRun/Attempt authority; no execution
or authorization authority change is made in this repair round.

## Evidence-supported disposition

The four identities are already present, once each, at
`quality/vulture-baseline.json:1001,1010,1072,1175`. They are retained APIs:
`backend/services/audit_bridge.py:186` invokes `audit_log.get_page` on the
production route path. The scanner excludes this BFF consumer because it is
outside `packages/*/src`. Removing those APIs would break pagination; duplicating
ledger entries would violate the exact multiset. The scan explicitly says a
candidate amendment cannot authorize new debt against trusted base
`c560d4ccad82`. The authorized ledger exception therefore offers no additional
valid amendment in this tree; a separately landed grant is required.

The integration command fails closed with nine missing producer conclusions.
It tests evidence aggregation, not the candidate services. Captured-check
extraction did not find check-run objects in the assumed dispatch structure;
a bounded second inspection was inconclusive. Recorded UNRESOLVED rather than
re-enumerating remote checks or inventing candidate successes. The supplied
hosted integration-scope failure cannot be diagnosed to a source change from
the available producer evidence. Do not alter the gate.

A fresh instrumented call to production `page_entries(limit=1)` visited every
row at both corpus sizes (100/100 and 10,000/10,000); see
`repair-memory-probe.log`. This confirms the initial-cost criterion is NOT MET
on the reachable unbound memory fallback (`audit_query.py:402`). Fixing that
requires mutation-aware indexing/store integration, not an unsafe cache keyed
by dict length. No speculative implementation change is bundled with the gate
repair. Frontend source retains 500 entries and mounts a viewport slice, but
runtime browser and byte-level heap bounds remain UNVERIFIED.

## Commands executed

All validation batches used 1,200-second timeouts.

- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — FAIL: trusted-base authorization, not an unbanked candidate identity.
- `uv run python scripts/check-integration-scope.py --event-name pull_request` — FAIL: nine missing candidate producer results.
- `node --test tests/ci/integration-scope.test.cjs` — PASS (not producer evidence).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` — 77 passed.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` — 45 passed, four PostgreSQL skips.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e` — PASS. This uses the registered E2E suite rather than the driver's invalid parent-suite path.
- `npm --prefix packages/hive-conductor/frontend run build` — PASS.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` — FAIL: daemon unavailable.
- Inline `PYTHONPATH=packages/hive-conductor/backend uv run python` counting-store probe — reproduced corpus-wide visits for a one-row request.

The supplied check-3 failure at `test_pm_workflow_api.py:271` has not been
re-run against the unidentified external service. Its array-shaped HTTP 200
is incompatible with the local route's `AuditPage` shape and canonical 403
contract. Local route/convergence tests exercise that contract successfully;
external candidate-stack acceptance remains UNVERIFIED.

## Acceptance matrix

| Criterion | Executed evidence / residual gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | Backend/core focused tests pass for SQLite/memory; PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before DB pagination | SQLite scoped queries and canonical route denial tests pass; external E2E driver reports failure. |
| Incremental loading and virtualization | Source inspected, production build passes; browser runtime UNVERIFIED. |
| Filters/export/retention without whole corpus in browser | Filtered/scoped export and retention metadata tests pass; retention lifecycle UNVERIFIED (`corpus_purge: none`, #325). Export is a direct download link, not JS accumulation. |
| Measured representative query/index strategy | Both million-row SQLite tests executed; VM work <2,800 legacy / 3,400 canonical. PostgreSQL UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row envelope | Focused backend/core suites execute these cases successfully for SQLite/memory; four PostgreSQL skips. |
| Initial page cost independent of corpus size | NOT MET on memory fallback; counting probe visits every row. SQLite indexed path passes deterministic work bounds. |
| Bounded browser memory/DOM rows | 500-entry retained window and viewport slicing inspected; browser execution/heap measurement UNVERIFIED. |

## Handoff

BLOCKED. Only this report changed; no production/test/ledger/grant edits and no
inventory delta. Preserve the existing implementation. A source repair to either
gate is not supported by the evidence. Required next inputs: separately landed
Vulture authorization, actual same-candidate producer failure diagnostics, and
an identified candidate stack for browser/PostgreSQL acceptance. Memory-path
cost and retention lifecycle remain substantive product acceptance gaps.

Progress: checked 1, done 0, skipped 0, errors 3 (Vulture authorization,
integration evidence, unavailable Docker). Do not redispatch the identical
inputs expecting another candidate-ledger amendment or documentation commit to
resolve these blockers. This report is committed locally; no push, PR mutation,
merge, destructive Git operation, or integration approval is performed.
