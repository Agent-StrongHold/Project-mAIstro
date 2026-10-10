# Issue #358 repair — 287bab

## Frozen scope

- Assigned issue: #358 only; branch `auto-358`, starting HEAD `5d927c879a1309c7bcc075b1a1f0cffbf816da40`, base `11376c7bef4ea7d17195b90bea8ca9a64a769bb1`; worktree initially clean.
- Snapshot: supplied dispatch-context.json (captured 2026-10-06), supplied check-0 through check-7 logs, prior result 366945. No GitHub mutations or re-enumeration.
- Repair candidates: `packages/hive-conductor/backend/services/audit_query.py`, adjacent audit tests and inventory note; reviewed retained Vulture identities in `quality/vulture-baseline.json` only if the exact gate requires them. Other audit implementation files, frontend, ADRs, and CI definitions are inspection/validation inputs, not blanket permission for unrelated repairs.
- Gates: exact Vulture command and integration-scope workflow; focused audit Python/browser validation where available, Ruff and suite inventory.

## Initial evidence and assumptions

- Driver check-3 failed on live `GET /v1/dag-runs` (500), not an audit endpoint. Do not change DAG execution to hide this failure.
- Driver check-6 requested `packages/hive-conductor/tests`, which has no collection recipe. Use registered suites, not gate changes.
- Prior result reports legacy ephemeral audit full scans and missing trusted-base Vulture authorization/integration producer artifacts. Treat these as hypotheses until reproduced.
- This is a writer repair round. Commit all changes locally; any remaining acceptance gaps must be explicit in the final verdict.

## Named gate checkpoint

- Exact Vulture command executed: FAIL, 1,340 findings, zero unclassified. Four `get_page` identities are already banked but absent from the trusted base (56332162cf63). The gate explicitly requires prior authorization; duplicating ledger rows or removing reachable APIs would not fix this evidence. No ledger edit warranted.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`: FAIL, nine missing producer results. The workflow requires same-candidate GitHub check runs; local aggregate unit tests cannot replace them. The supplied dispatch check-run snapshot is the only remote evidence considered.
- Read ADR-073, ADR-081226-69ee, ADR-081226-7248: retain admin-only canonical decision audit and canonical execution/event authority. No execution or authorization repair is allowed here.
- Legacy JsonStore exposes mutable records and multiple mutation paths. A read-cache heuristic would produce stale ordering/scope after same-length or in-place mutation; do not introduce one merely to pass an envelope test.
- Dispatch check-run evidence is for **84081fba82fc**, not the assigned head. It shows integration-scope and all nine specialized producers successful on that older SHA. It cannot identify the reported last merge-queue failure or authorize candidate success. The named remote failure is UNRESOLVED without its same-candidate evidence. First parsing attempt used the wrong JSON shape; second succeeded; no re-fetch.
- Docker probe with the specified socket FAILED: daemon unavailable. PostgreSQL and Docker-dependent validations cannot be claimed.

## Executed acceptance validation

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **78 passed**. Real authenticated HTTP routes, scope isolation, core bridge, filter/export, maximum size, empty pages, tied timestamps and concurrent inserts are covered.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/persistence/test_sqlite_audit.py packages/maistro-core/tests/persistence/test_pg_audit.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: **76 passed, 5 skipped**. Skips do not count as PostgreSQL evidence.
- Legacy SQLite million-row envelope: index migration **8.429s**, first page **0.0006s**, scoped page **0.0004s**, maximum **<2,800 VM instructions**. Canonical SQLite: million-row load **7.859s**, maximum **3,400 VM instructions**.
- `uv run pytest tests/migrations/test_audit_cursor_indexes.py -x -q`: **2 passed**.
- Fresh `uv run python` structural probe using real `JsonStore`, `page_entries(limit=1)` and `sys.setprofile` on `_created_at_of`: **100/100** and **10,000/10,000** records inspected. Thus the legacy ephemeral first-page cost is still corpus-dependent; this is reproduced evidence, not the previous worker's assertion.
- `npm --prefix packages/hive-conductor/frontend run build`: **PASS**, TypeScript and production Vite bundle. Browser runtime not executed; build success is not virtualization proof.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**. Tests verify aggregator semantics only; not same-candidate producer success.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`: **PASS**.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e`: **PASS**, counts 3,456 / 13,944 / 23. No tests added or removed, hence no inventory delta or baseline/grant edit.

## Acceptance disposition

| Criterion | Evidence / remaining gap |
| --- | --- |
| Bounded stable cursor pages and maximum size | Focused HTTP/core/SQLite tests PASS. |
| Authorization/scope filters before database limit | SQLite and authenticated HTTP tests PASS; PostgreSQL execution UNVERIFIED. Canonical decision audit remains admin-only per ADR-073. |
| Incremental loading and virtualization | Source uses 100-row requests, a 500-record sliding window and virtual rows; production build PASS. Browser execution UNVERIFIED. |
| Filters/export/retention without whole-browser corpus | Scoped capped streaming export/filter tests PASS. Retention endpoint reports `corpus_purge: none`; #325 owns purge. Do not count metadata as a working retention purge. |
| Representative query/index measurements | Both million-row SQLite envelopes executed above; PostgreSQL UNVERIFIED. |
| Concurrent inserts, stable cursors, isolation, maximum limit, empty pages, million-row envelope tests | Focused executed backend/core/SQLite tests PASS. |
| Corpus-independent initial page cost | Durable SQLite/core ephemeral tests PASS; legacy ephemeral path FAILS structural probe. |
| Bounded browser memory/DOM | Source has caps; runtime and byte-level heap behavior UNVERIFIED. |

## Handoff

**BLOCKED**. No safe code/ledger repair of the named gates is justified by the supplied evidence: the four reviewed public APIs are already banked, and candidate ledger edits cannot grant authorization. The supplied remote integration results describe a different SHA and do not identify the failing producer. No gates, authorization, execution paths or audit authorities changed.

Only this report changed. No production repair claimed. The legacy ephemeral defect requires a deliberate mutation-aware indexing contract, not a freshness heuristic over mutable records. No work discarded. Commit this handoff locally and leave the tree clean.

Next prerequisites: provide same-candidate failed integration producer evidence and trusted-base API authorization; repair the legacy mutable-store read complexity with complete mutation coverage; provision PostgreSQL/browser acceptance validation; reconcile retention with #325.

Progress: {checked: 1, done: 0, skipped: 0, errors: 2, next: named gate prerequisites and legacy ephemeral indexing}.


