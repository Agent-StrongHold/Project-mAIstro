# Issue #358 — aeec repair checkpoint

## Frozen scope

- Single item: issue #358, branch `auto-358`, starting head
  `49d3c3439cebb7339fde3d0a711f8aec3c8a1db5`, supplied base
  `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.
- Repair only observed integration-scope/vulture failures and audit pagination
  acceptance gaps. Candidate implementation files are the existing audit routes,
  audit query/bridge/store adapters, core audit paging/stores, AuditLog UI and their
  adjacent tests; CI workflows/scripts are inspection only, not gate weakening.
  This report and an inventory note (if tests change) are the documentation scope.
- No re-fetch/re-enumeration of issues or PRs. Supplied dispatch is evidence only.
- Initial worktree clean; assigned head resolved exactly.

## Observed evidence

Driver check-1/check-2 passed lint/format. check-4 passed 91 backend tests.
check-3 failed because the external E2E service reports MaistroCoreBridge but
returns an unpaginated legacy audit array to a non-admin (expected 403).
Assumption: service version/configuration may differ from this worktree; establish
that before changing assertions. check-6 is an invalid suite-inventory invocation
(no collection recipe for packages/hive-conductor/tests), not a test failure.
Prior result records missing integration producer results and unavailable Docker;
these claims will be rechecked rather than adopted.

## Checkpoint 1

- Exact requested Vulture command passed: 1,326 reviewed identities, 1,326
  findings, zero unclassified. No ledger amendment is justified by this scan.
- Docker daemon check failed: cannot connect to unix:///var/run/docker.sock.
- Dispatch check-run evidence is for `bc293cd790b6852da71b3e251dcecdda84bbde9b`,
  not the assigned head or a failed merge-group candidate. Its integration-scope
  and all specialized producers succeeded. The named remote failure has no
  matching failed-candidate log in this evidence. UNRESOLVED: cannot repair an
  unspecified producer failure by inventing results or changing the aggregator.
- Production audit route returns an AuditPage and denies canonical non-admin
  access before query. The driver's legacy array cannot be this route's output.
  No assertion relaxation is appropriate.

## Checkpoint 2 — executed validation

- Backend selection initially errored before test execution because pytest could
  not allocate `/tmp/pytest-of-dev/pytest-*`. Repeated with a verified-new
  job-local `--basetemp`: **91 passed** (`worker-backend-isolated.log`). No temp
  files or existing work were removed. Legacy million-row index build 10.061s;
  first page 0.0007s, scoped page 0.0005s; query work <2,800 VM instructions.
- Core audit pages + workspace scope conformance: **50 passed, 4 skipped**
  (`worker-core.log`). Canonical SQLite million-row load 8.615s; maximum query
  work 3,400 VM instructions. PostgreSQL cases skipped without a configured DSN.
- `uv run ruff check .` and `uv run ruff format --check .`: pass (3,196 files).
- `uv run python scripts/check-api-route-contracts.py`: pass (284 handlers,
  15 audited routes, zero canned responses).
- Registered inventory command `--suite packages/hive-conductor/tests/e2e`:
  pass (23 tests). Driver's parent-directory suite name is invalid.
- Measured CI scope from the assigned base requires docker-build, Hive API/UI
  E2E, PostgreSQL pg17/pg18, wheel-imports. Named integration-scope command fails
  for six missing results (`worker-integration-scope.log`). This fail-closed
  diagnostic is not a reproduction of an unidentified remote producer defect.
- Gate logic/parity tests: **53 passed** (`worker-gate-tests.log`).
- `cd packages/hive-conductor/frontend && npm run build`: pass
  (`worker-frontend-build.log`), not browser runtime evidence.

Read ADR-073 and ADR-081226-9944: Sentinel decision audit stays admin-only;
legacy personal scope is only the unbound fallback. Audit pagination is a read
projection, never another execution or authorization authority. Purging remains
explicitly absent and assigned to related issue #325; this issue exposes bounded
retention metadata rather than claiming a purge policy has been implemented.

## Final acceptance review

Production trace inspected: registered audit route -> authorized core bridge ->
existing AuditLog.get_page -> SQL adapters' shared page_query; unbound fallback
uses stores.audit_log = IndexedAuditStore with durable indexes initialized before
traffic. Frontend requests 100 rows at a time, caps retained entries at 500,
slices fixed-height rows with overscan, and uses a native export link rather than
fetching an export Blob. Existing browser tests check late-response isolation,
short-page continuation, eight-page traversal with <=30 mounted rows, and native
filtered downloads, but none was executed against this candidate this round.

| Acceptance criterion | Executed evidence / limit |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | 91 backend + 50 core/boundary tests passed. Shared production query limits pages to 200 and orders timestamp/row identity; legacy orders created_at/id. |
| Authorization/scope filters before DB pagination | Denial-before-query, actor isolation, exact-org and filtered-page tests passed; route/bridge/SQL inspected. ADR-073 canonical audit remains admin-only. |
| Incremental frontend loading and virtualization | TypeScript/Vite build passed, production component and adjacent browser assertions inspected. Browser runtime **UNVERIFIED**. |
| Filters/export/retention without browser corpus load | Backend lazy, capped, scoped NDJSON and retention metadata tests passed. Native filtered browser download **UNVERIFIED**. Actual corpus purging remains absent (#325), not claimed implemented. |
| Measured query/index strategy on large datasets | Two real million-row SQLite tests passed with deterministic VM-work ceilings, including deep ties, sparse filters, and absent scopes. PostgreSQL **UNVERIFIED**. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row envelope | SQLite/memory cases executed and passed; four PostgreSQL cases skipped. |
| Initial-page cost independent of corpus size | SQLite VM bounds and memory no-enumeration/read-budget tests passed. Index build cost measured separately from page reads. |
| Bounded browser memory and DOM row count | Implementation caps and browser tests inspected; runtime **UNVERIFIED**. |

Additional migration validation: `uv run alembic heads` returns only `062 (head)`;
audit-index and chain test selection: **2 passed, 18 skipped** (live PostgreSQL
unavailable). `git diff --check`: pass.

## Disposition and handoff

**BLOCKED**. No production defect requiring a code or ledger change was
established in this repair round. Only this report changed; no new tests means
no inventory delta note is required. Existing implementation and strict E2E
assertions are preserved. No gates, grants, ledgers, branches, or remote state
were mutated, and no background processes were started.

Required next input: the actual failed integration-scope candidate SHA and its
producer results/logs (the supplied snapshot instead contains a success on a
different head). Required environment: a known deployment of this candidate for
API/browser E2E and available PostgreSQL for live query/migration checks. Do not
substitute unrelated-head success or a stale external legacy endpoint for that
evidence. Docker daemon unavailability prevents the advertised compose path.

Progress: checked 1, done 0 implementation repairs, skipped 0, errors 1 unresolved
integration-evidence blocker. Validation/report complete; next: supply matching
failed-candidate evidence and live services. This report is committed locally;
no integration approval or issue closure is implied.
