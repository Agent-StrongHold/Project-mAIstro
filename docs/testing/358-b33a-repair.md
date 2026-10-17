# Issue 358 repair — b33a

## Frozen scope

One item: issue #358 / PR #1712, branch `auto-358`, starting HEAD
`9de533983617edd8047f7c62a9148b5c43e64159`, supplied develop base
`6138e9eac1465775b1cd0d37447b5ce5dba1fdd3`.
No GitHub mutation or re-enumeration. Worktree initially clean.

Repair candidates are the existing audit pagination production/test files,
`packages/hive-conductor/tests/e2e/test_pm_workflow_api.py`, their inventory
notes, and this evidence file. Integration-scope configuration and vulture
ledger are inspection targets; ledger changes only for executed findings.
Do not modify unrelated production behavior or weaken gates.

## Initial evidence

Read supplied check logs: checks 0/1/2 pass dependency sync/lint/format;
check-3 fails `TestAuditTrail::test_audit_log_has_entries` because an HTTP
server returns a legacy array/200 where canonical health leads the test to
expect 403. Whether the external service is current is not established.
Check-4: 91 audit backend tests pass. Check-5/7 inventory passes. Check-6
fails because `packages/hive-conductor/tests` has no collection recipe.
The prior artifact reports a similar external-service failure; earlier
verification claims are not accepted as current evidence.

Ambiguity: dispatch names integration-scope without its failing output.
Assumption: reproduce the gate with workflow arguments and supplied refs
before deciding whether there is an in-scope repair.

## Executed gate diagnosis

- Exact requested vulture command passed: 1,326 reviewed identities and 1,326
  findings, zero unclassified or never-allowlist findings. No ledger edit justified.
- Reproduced integration scope using workflow's no-renames three-dot diff
  against the supplied base and the latest check IDs in the frozen dispatch.
  Required: docker-build, both PostgreSQL legs, wheel-imports, both Hive E2E legs.
  `check-integration-scope.py --event-name pull_request --scope-json ...
  --result ...` exits 1 solely because captured `docker-build=in_progress`.
  The remaining required captured checks succeeded. Captured integration-scope
  itself has no conclusion. This is incomplete remote evidence, not proof of
  a candidate code defect; no gate or workflow changes justified.
- Dispatch also captures lint-and-type-check and Quality gate failures without
  their diagnostic logs; not inferred to be caused by this lane.
- First dispatch extraction hit an AttributeError because check-runs data is a
  list rather than an object; corrected locally, no repository code changed.

## Focused acceptance results

Read repository instructions and accepted ADR-068/073. Canonical decision
audit remains admin-only before store access; the unbound legacy trail uses
actor scope in SQL. No scheduler, authority, policy, or authorization change.

Executed against this checkout:

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_degraded_mode_surface.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **91 passed**, `/tmp/358-b33a-backend.log`. Includes the exact external PM
  audit assertion executed against real candidate routes/auth and both
  canonical and legacy bindings (test_audit_convergence.py:470).
  Million-row legacy SQLite index migration 9.007s; first page 0.0006s;
  scoped page 0.0004s; max query VM instructions <2,800.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: **50 passed, 4 skipped**, `/tmp/358-b33a-core.log`.
  Canonical SQLite million-row load 7.445s, max VM instructions 3,400.
  All four PostgreSQL cases explicitly unverified (no configured test DSN).
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps ...`: failed to connect
  to daemon. Cannot provision PostgreSQL or the compose E2E stack here.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3,205 files).

- `uv run pytest tests/migrations/test_audit_cursor_indexes.py
  tests/migrations/test_migration_chain.py -x -q`: **2 passed, 18 skipped**.
  PostgreSQL-backed migration execution is unverified.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: passed, 3,599 identities.
- Same inventory command with `--suite packages/maistro-core/tests`: passed,
  15,795 identities. Driver check-6 used a nonexistent collection recipe;
  do not invent one or change inventory to hide that invocation error.
- `npm --prefix packages/hive-conductor/frontend run build`: passed both
  TypeScript configurations and Vite production compilation. Browser runtime
  tests NOT executed against this candidate; build success is not DOM evidence.
- Read-only GET `http://localhost:8101/openapi.json` confirms external service
  declares `/v1/audit` response as `type: array`, unlike the candidate's
  `AuditPage` route annotation (`backend/routes/audit.py:118`). This explains
  the driver's legacy-array response: it is not serving this candidate's API
  contract. Do not loosen the correct bounded-page assertion to accept it.

## Acceptance reconciliation

| Criterion | Current executed evidence / gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | 91 backend + 50 core/scope tests pass, including duplicate timestamp ties, concurrent inserts, malformed cursors, limit ceiling/floor and empty pages. PostgreSQL runtime UNVERIFIED. |
| Scope filters before database pagination | Legacy SQLite SQL scope/alias tests and canonical admin-before-I/O tests pass; core org/user filtering tests pass. Accepted ADR-073 requires admin scope for canonical decisions, not a new personal authorization path. PostgreSQL runtime UNVERIFIED. |
| Incremental frontend loading and virtualization | Production source has generation-guarded cursor loads, a 500-entry sliding window and viewport slicing; TypeScript/Vite build passes. Existing Playwright tests (pm-workflow.spec.ts:239–353) inspect late responses, repeated sentinel visibility and <=30 mounted rows. Browser execution UNVERIFIED this round. |
| Filters, export, retention avoid browser corpus loading | Executed backend scoped/filter/export-cap/retention tests pass. Production UI uses a native download link rather than buffering an export Blob. Native download test (pm-workflow.spec.ts:355) inspected but browser execution UNVERIFIED. Corpus purge is explicitly #325's separate scope, reported honestly as `none`, not claimed implemented. |
| Representative query/index measurements | Both real million-row SQLite tests pass with measurements above and deterministic query-work bounds. PostgreSQL million-row EXPLAIN/BUFFERS test UNVERIFIED (skipped). |
| Concurrent inserts, cursor stability, scope, max, empty, million-row tests | Executed focused tests cover all named cases for memory/SQLite, including acknowledged concurrent writes; PostgreSQL cases skipped. |
| Initial page independent of corpus size | SQLite million-row first/deep/scoped queries stay within deterministic VM budgets; indexed memory tests prohibit corpus enumeration. PostgreSQL runtime UNVERIFIED. |
| Bounded browser memory/DOM | 500 retained-entry cap and viewport row slice inspected; compilation passes. Browser execution UNVERIFIED; source alone does not prove this definition of done. |

## Disposition and handoff

**BLOCKED**, not merge-ready. No evidence-supported production repair or
vulture ledger amendment was found. Only this evidence file changed; no new
tests or suite-count changes, so no inventory delta is needed. No remote
mutation, merge, authority change, or gate weakening performed.

To unblock: provide completed required docker-build evidence and diagnostic
logs for the reported integration failure; provide a working local Docker
endpoint/test PostgreSQL DSN and a fresh candidate HTTP/UI service. Then rerun
the named PostgreSQL/migration cases and the existing audit Playwright tests.
The existing service on port 8101 must not be counted as candidate evidence.
Captured unrelated lint/type and Quality gate failures remain unresolved
without diagnostics; no speculative edits made.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1,
next: "infrastructure and completed CI evidence; candidate browser/PostgreSQL validation"}.
The assigned item is explicitly blocked; no new items started.
