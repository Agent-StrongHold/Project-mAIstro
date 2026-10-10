---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair checkpoint — 02b69f

Frozen scope: issue #358 only; supplied HEAD
`32492cbc31e18f6e7f1ef66492460d2b4ae5d56e`, base
`31d891a561dffd6db1312ea4a85c4835c8048440`, supplied dispatch and check-0 through
check-7 logs. No GitHub mutation or refresh. Initial worktree clean.

Files in scope: existing #358 audit routes/query/bridge, core audit pagination,
AuditLog frontend and their adjacent tests; integration-scope workflow/gate
inspection; quality/vulture-baseline.json only if the exact scan provides evidence;
this checkpoint. Other issue work and historic repair notes are not repair targets.

Initial evidence: supplied check-3 fails at test_pm_workflow_api.py:271 (expected
403; external HTTP service returns legacy audit list). check-6 names an
unregistered inventory suite. Prior result reports integration-scope producer
HTTP 500s and unapproved retained Vulture identities. These are evidence to
revalidate, not permission to weaken assertions or gates.

Assumption: writer assignment applies. The dispatch preflight string-index error
is driver-side unless repository evidence demonstrates otherwise. Do not modify
the driver or infer its successful repair from repository validation.

## Fresh named-gate evidence

Exact requested Vulture scan executed: failed with 1343 findings versus 1339
trusted identities at resolved base `35f2e0158a91`. The four retained `get_page`
methods (PgAuditLog, SqliteAuditLog, AuditLog protocol, InMemoryAuditLog) already
exist in the candidate ledger. No unbanked candidate identity was reported.
Trusted-base authorization cannot be supplied by adding duplicate ledger rows.
No ledger amendment or grant change is justified by this scan.

Read ADR-073 (Accepted): canonical Sentinel decision audit is admin-scoped.
Legacy actor-scoped pagination must not replace that authorization rule.
Read production audit route/query and adjacent backend/core/browser tests.
The supplied integration-scope workflow requires real producer success; its
unit checks cannot substitute for missing producer outcomes.

Integration scope: `uv run python scripts/check-integration-scope.py
--event-name pull_request` failed (nine required outcomes missing); `node --test
tests/ci/integration-scope.test.cjs` passed 12 tests. Frozen dispatch check-runs
for linked PR head `3a9865527991` show integration-scope failed, docker-build
skipped, workflow-lint and lint-and-type-check failed. No fresh remote outcomes
are available for starting HEAD; no outcomes fabricated and no gate weakened.

Focused backend validation: `uv run pytest` of test_audit_convergence.py,
test_audit_pagination.py, test_audit_routes.py and test_noop_route_contracts.py
with `-x -q -s`: **76 passed** (24.63s). Real million-row SQLite index migration
11.907s; initial page 0.0007s; scoped page 0.0004s; maximum query work <2800 VM
instructions. Log `/tmp/358-02b69f-backend.log`.

Core validation: `uv run pytest` of persistence/test_audit_pages.py and
workspaces/test_store_boundary_scope_conformance.py with `-x -q -s`: **45 passed,
4 skipped** (no PostgreSQL DSN). Canonical million-row SQLite load 9.800s;
maximum measured query work 3400 VM instructions. Log
`/tmp/358-02b69f-core.log`. `uv run ruff check .` and `uv run ruff format --check .`
passed (2913 files). First inventory run rejected this note's inline empty-map
syntax; corrected to indented explicit zero suite deltas before rerunning.

Inventory rerun passed for the three registered suites: backend 3385, e2e 23,
core 13064. The driver's `packages/hive-conductor/tests` parent path has no
recipe; `packages/hive-conductor/tests/e2e` is the correct existing recipe.
No baseline or driver edits made. `npm exec -- tsc --noEmit` in the frontend
passed; this is type checking, not browser execution.

A fresh read-only GET of `http://localhost:8101/openapi.json` returned 200:
audit GET exposes only action/severity/actor, answers an array, and has neither
export nor retention routes. This external service demonstrably does not serve
the candidate audit contract. It was not restarted, changed, or used as passing
candidate evidence. Existing backend convergence tests execute the PM audit
assertion through real candidate routes with both legacy and canonical binding;
those passed within the 76-test run. Do not change the PM assertion to accept
this stale service's security behavior.

## Acceptance assessment

- Bounded cursor pages, stable ordering, maximum page size: **executed**, focused
  route and real SQLite/memory adapter tests pass (200-row ceiling, ties,
  malformed cursors, end-of-walk empty pages).
- Scope/authorization before DB pagination: **executed**, scoped SQL and
  canonical refusal-before-query tests pass; ADR-073 admin-only decisions remain
  authoritative. No new scheduler, execution authority, Goal/event store, or
  authorization path introduced.
- Incremental loading and virtualization: inspected production AuditLog.tsx and
  its routed Playwright regressions; **browser execution UNVERIFIED**. Component
  requests 100 rows, retains at most 500 entries, renders viewport plus overscan.
- Filters/export/retention without browser corpus loading: filtering, capped
  NDJSON export, and retention metadata backend tests pass. Production export is
  a download link, not a JS whole-corpus buffer. **Browser download and actual
  corpus retention UNVERIFIED**: audit_query.py:79 advertises no purge (#325).
- Representative large datasets/query indexes: **executed**, both real SQLite
  million-row envelopes pass with deterministic query-work bounds stated above.
  **PostgreSQL UNVERIFIED**, four variants skipped because no DSN was supplied.
- Concurrent inserts, cursor stability, scope isolation, maximum, empty pages,
  million-row envelope: **executed**, covered within 121 passing focused tests.
- Corpus-independent initial page cost: proven for measured durable SQLite
  seeks after startup indexing, **not satisfied universally**. The supported
  in-memory fallback snapshots/sorts the full corpus at audit_query.py:403-404.
- Bounded browser memory/DOM: implementation caps inspected; **browser execution
  UNVERIFIED**. A retained row-count cap is not an arbitrary-payload byte bound.

## Blocked handoff

Only this inventory/evidence note changed. No production repair is claimed:
actual named-gate evidence does not justify a code, workflow or ledger change.
Four live core pagination APIs are already banked at
quality/vulture-baseline.json:1002,1011,1073,1172; their production caller is
backend/services/audit_bridge.py:186. Removing/renaming them to dodge Vulture or
adding duplicate ledger rows would not be a legitimate repair. Trusted-base
approval must be handled separately by the campaign owner.

Integration-scope still requires successful actual producers; frozen dispatch
records upstream failures/skips, and the previous artifact attributes
workflow-lint to HTTP 500 downloads. That download cause was not independently
reexecuted here. No rerun or GitHub mutation attempted. The driver preflight
`string indices must be integers, not 'str'` remains **UNRESOLVED**: supplied
repository checks do not reproduce it and this lane does not own the driver.

Next: campaign owner resolves trusted-base authorization and driver preflight,
then obtains fresh required producer results against a candidate-built isolated
service. Retention/in-memory cost gaps still require acceptance reconciliation;
no claim of complete #358 acceptance or integration approval is made.

Progress: checked 1 assigned issue, done 0 repairs, skipped 0 issues, blocked 1.
Preserved all incoming implementation. This checkpoint is committed locally;
no pushes, GitHub mutations, destructive Git operations, gate weakening, or
grant edits.
