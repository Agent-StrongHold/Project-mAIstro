# Issue #358 repair — 08fa

## Frozen scope and initial evidence

Only issue #358; assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`, clean starting HEAD `352dd500243cefd8618af0b683443c930f0dc046`,
base `34795962548a33f6b6f7e1234dcea201a9df96ef` (resolved locally).
No remote mutations, no new issue/PR enumeration, no discarded work.

Process the supplied audit pagination implementation, its adjacent audit tests,
the failing `test_pm_workflow_api.py` audit contract, and the named
integration-scope/vulture gates. Potential edits restricted to those tests,
audit implementation if a reproduced defect requires it, reviewed vulture
ledger identities if the exact scan requires them, and this note plus an
inventory note. No unrelated implementation work.

Supplied check logs read: ruff check/format passed; 84 focused backend tests
passed; core/backend inventories passed. `check-3.log` failed at
`test_pm_workflow_api.py:271`: expected canonical 403 but export returned 200
with a legacy array. `check-6.log` reports no collection recipe for
`packages/hive-conductor/tests`. Prior result reports PostgreSQL/browser
acceptance not fully verified and missing integration-scope producer evidence.
These are evidence to reproduce, not trusted claims of current correctness.

Ambiguity: named integration-scope failure has no specific failed producer in
the prompt. Inspect the supplied dispatch evidence and local workflow once;
if no resolvable candidate evidence exists, report it unresolved rather than
altering a gate. Treat the E2E's configured HTTP target as potentially stale
until its fixture and reachable implementation are checked.

## Reproduced evidence / repair decision

- Exact vulture command passed: 1,328 reviewed identities = 1,328 findings;
  zero unclassified. No ledger amendment is warranted.
- `uv run pytest packages/hive-conductor/backend/tests/test_degraded_mode_surface.py
  -x -q`: 6 passed, one failed at line 221, expecting anonymous audit 200 but
  receiving 401. This is the adjacent audit test explicitly identified in the
  supplied prior result and falls within this round's frozen adjacent-test scope.
  Repair that fixture/expectation, not the production authorization boundary.
- Read repository instructions, accepted ADR-073 (canonical audit admin-only)
  and ADR-081226-9944 (single canonical hierarchy). No execution or audit
  authority changes are planned. Audit pagination remains a read projection.
- Docker daemon probe failed at `unix:///var/run/docker.sock`; no PostgreSQL
  runtime claim can be made on that basis.
- Second/final ambiguity inspection: supplied dispatch check runs show success
  for all relevant specialized producers and integration-scope on historical
  `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not this candidate. Failing merge-group
  candidate and producer log are not supplied: UNRESOLVED. No gate changes.
- E2E uses external `HIVE_BASE_URL` (default localhost:8101), not the checked-out
  ASGI application. Current route always exports NDJSON, never a JSON array;
  supplied failure's response is incompatible with this implementation.
  Do not loosen its 403 expectation to accept that older server contract.

## Implementation and focused validation checkpoint

Changed only the adjacent recovery test and this round's documentation. The
recovery test now generates a real optional-router degradation event, mounts
production AuthMiddleware on the remounted router, proves anonymous 401, then
uses the real admin-login fixture's cookie to assert a one-row audit envelope
and the event's target/system actor/warning severity. No mocked principal and
no authorization relaxation. Existing collected count unchanged (delta 0).

Executed with 1,200-second timeouts:

- `uv run pytest packages/hive-conductor/backend/tests/test_degraded_mode_surface.py
  packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **91 passed**. Million-row legacy SQLite index migration 10.008s, initial
  page 0.0007s, scoped page 0.0004s, query VM work <2,800 instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: **50 passed, 4 skipped** (PostgreSQL service-dependent cases).
  Canonical SQLite million-row load 9.152s, maximum query work 3,400 VM steps.
- `uv run pytest tests/test_check_integration_scope.py -x -q`: **18 passed**.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**.
- `uv run python scripts/check-integration-scope.py --event-name pull_request
  --required-json`: resolves nine required specialized checks. This is policy
  resolution, NOT proof the exact candidate's producers succeeded.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`:
  all passed (3,168 formatted Python files).

## Broader validation checkpoint

- `uv run pytest packages/hive-conductor/backend/tests -x -q`:
  **3,576 passed, 19 skipped**, 6 warnings, 170.87s. The prior full-suite blocker
  is repaired; no new failure appeared. Skips are not claimed as acceptance.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
  --suite packages/maistro-core/tests`: passed at 3,595 / 23 / 15,423 collected
  cases. The registered E2E key fixes the supplied command's unsupported path;
  no inventory recipe or baseline was edited.
- `uv run python scripts/check-api-route-contracts.py`: passed, 284 handlers,
  15 audited routes, zero canned.
- `npm --prefix packages/hive-conductor/frontend run build`: TypeScript/Vite
  passed. Generated output remains ignored; no build artifacts committed.
- Re-executed the supplied prior job's `audit-browser-probe.cjs` unchanged
  against this worktree's actual AuditLog component in Chromium. Assertions
  before line 61 passed: eight pages / 800 rows, 500 retained rows, <=30 mounted
  rows, cursor sequence, refresh, and action filtering. Command then failed at
  `download.path: canceled`. This is controlled-API component evidence only,
  not a passing E2E or completed native download. Do not weaken the probe to
  hide the failure. Live authenticated browser export remains UNVERIFIED.

## Acceptance matrix and handoff

| Acceptance | Executed evidence / limitation |
| --- | --- |
| Bounded cursor, stable order, maximum page size | Focused backend 91 passed; core 50 passed, including ties, malformed cursors, maximum/floor and page continuation. |
| Authorization/scope before DB pagination | SQLite scoped-query and canonical deny-before-query tests passed. Repaired recovery test uses production session middleware. PostgreSQL runtime UNVERIFIED (four core skips). |
| Incremental loading and virtualization | Re-executed Chromium component assertions passed eight pages; frontend build passed. Authenticated routed browser E2E UNVERIFIED. |
| Filters/export/retention without browser corpus load | Backend bounded NDJSON/filter/retention tests passed; Chromium filter and download-link behavior reached native download. Native download completion UNVERIFIED: probe failed with cancellation. No retention/purge policy change (#325 owns purge). |
| Representative large-data query/index measurement | Real legacy and canonical SQLite million-row tests passed with deterministic VM-work bounds and timings recorded above. PostgreSQL million-row performance UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | Existing backend/core regressions executed successfully on SQLite/memory, including threaded writes and sparse/deep filter queries. PostgreSQL skipped. |
| Initial page bounded independently of corpus size | SQLite VM-work assertions and production-memory scan/slice rejecting regressions passed at 100 and 10,000 rows. PostgreSQL runtime UNVERIFIED. |
| Browser memory/DOM row count bounded | Component probe reached 800 loaded, 500 retained, <=30 mounted. No browser heap-byte measurement or live-app E2E claim. |

Final named gate invocation: `uv run python scripts/check-integration-scope.py
--event-name pull_request` exited **1** with all nine required producer results
missing. Deliberately supplied no fabricated results; historical success is not
this candidate's success. Its policy tests pass, but integration-scope readiness
remains blocked until exact-candidate producer evidence is available. Final
ruff check/format and diff whitespace checks passed again.

Changed files this round:

1. `packages/hive-conductor/backend/tests/test_degraded_mode_surface.py`
2. `docs/testing/inventory-notes/358-08fa-audit-recovery.md` (delta 0)
3. This report, `docs/testing/358-08fa-repair.md`

No production code, gates, ledger/grants, ownership, or authorization paths
changed. Existing branch work preserved. Local commit is a repair handoff, not
integration approval; no GitHub mutations.

Verdict: **BLOCKED**. One concrete, reproduced adjacent test defect repaired;
full backend suite now passes. Remaining blockers are missing exact-candidate
integration evidence, unavailable Docker/PostgreSQL execution, and incomplete
live browser/native export validation. The driver E2E must target this candidate,
not the older JSON-array export server. No speculative repair is justified.

Progress: checked 1 issue, done 1 test repair, skipped 0 issues; 3 remaining
validation blockers above. Next: supply the failing merge-group candidate and
producer log; validate PostgreSQL and authenticated browser export against this
candidate; use the registered E2E inventory key. Do not repeat blind ledger
edits or relax the audit contract to match a foreign HTTP service.
