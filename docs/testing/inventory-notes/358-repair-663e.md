# Issue #358 repair — job 663e73fd

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD verified: `54016818d6402baaf6e0493e036146b3cca45b82`;
  supplied base: `8c8fc8d6706a0837bd991c4e92138bf4d776ac9e`.
- Only issue #358: inspect existing audit pagination implementation/tests,
  relevant ADRs, named integration-scope and exact vulture gates, and driver
  checks 0–7. No GitHub mutations or changes to unrelated lanes.
- Candidate edits limited to this evidence note and evidence-backed repairs in
  existing #358 audit files or the explicitly permitted vulture ledger.
- Worktree was clean on arrival; no incoming edits required salvage.

## Initial evidence

Driver check-3 fails at `test_pm_workflow_api.py:271`: live `/v1/audit`
returns an unpaginated JSON array and HTTP 200 where canonical audit expects
403. Do not weaken the assertion to accommodate an unidentified live server.
Driver checks 1/2 pass lint/format; check-4 passes 58 focused backend tests;
check-6 fails because `packages/hive-conductor/tests` has no inventory recipe.
Prior result records missing integration producer results and four vulture
identities lacking trusted-base authorization. These claims will be rerun.

Ambiguity: the job provides a repair assignment but no producer job artifacts
for integration-scope. Proceed with the gate's actual available evidence;
never fabricate successful producer statuses.

## Gate checkpoint

Exact requested vulture scan rerun: exit 1, 1363 findings, zero unclassified.
Four `get_page` identities require trusted-base authorization (pg_audit.py:49,
sqlite_audit.py:96, protocols/memory.py:404, sentinel/audit.py:42).
The caller at `backend/services/audit_bridge.py:186` is a direct production
protocol call outside the gate's `packages/*/src` scan roots. These methods are
not dead; removing them or inventing in-scan calls would not be a valid repair.
The gate explicitly says candidate ledger updates cannot authorize the debt.

ADR-073 read: canonical decision audit must remain admin-scoped; retain the
403 assertion. Attempted ADR-062 filename was not found; skipped that filename
and then resolved/read `ADR-062-graph-execution-protocol.md`, including its
canonical durable-execution clarification. No execution authority changes.

## Fresh validation (1200-second test timeout)

- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2776 files).
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  failed; all nine specialized producer results missing. No supplied artifact
  identifies which remote producer caused the reported failure. This local
  invocation proves missing local evidence, not the remote failure's cause.
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}}'`:
  failed, cannot connect to Docker daemon. No attempt to use/truncate an
  unidentified shared PostgreSQL database.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 PostgreSQL cases skipped (no test DSN).
  Actual canonical SQLite million-row load: 8.603s; maximum query work 3400 VM
  instructions across equality filters and deep cursor/timestamp ties.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  58 passed. Legacy million-row startup index migration: 8.892s; initial/scoped
  page: 0.0007s/0.0004s; maximum query work below 2800 VM instructions.

The candidate ledger already has all four reviewed retained identities at
`quality/vulture-baseline.json:1021,1030,1089,1188`. No missing candidate entry
or eliminated identity was reported. Duplicating those entries would corrupt
bookkeeping, not provide authorization. The explicit ledger amendment exception
does not permit trusted-base grant edits or gate weakening. Ledger unchanged.

## Acceptance review

Read actual production route, bridge, query and frontend implementations plus
canonical adapter tests and convergence tests. The saved failing PM assertion
also executes in-process against both real production bindings in the passing
convergence suite. The external PM module defaults to `http://localhost:8101`;
the driver response is not this candidate's paginated route contract. Do not
change its expected 403 or pagination shape to make that service pass.

| Acceptance criterion | Executed evidence and remaining limits |
| --- | --- |
| Bounded cursor pagination, stable order, maximum page size | Passing canonical SQLite/memory and legacy backend tests; max 200 plus lookahead, timestamp/id ties and malformed/empty/past-end cursors. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Passing real-route denial-before-query tests and SQLite exact-org/actor/filter tests. ADR-073 admin-only canonical audit remains intact. |
| Incremental loading and virtualization | `AuditLog.tsx` inspected: cursor requests, virtual row slice, 500-entry retained window. Browser execution UNVERIFIED. |
| Filters/export/retention without browser corpus | Passing filter/export parity and cap tests; native download link inspected. `audit_query.py:79` explicitly declares no purge; actual retention operation absent, not proven by metadata endpoint. |
| Representative large dataset/index measurements | Both million-row SQLite query paths measured above using deterministic VM-work budgets. PostgreSQL runtime UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | Focused tests pass for SQLite/memory; four PostgreSQL cases skipped. |
| Initial cost independent of corpus | SQLite read work bounded after startup indexes. `audit_query.py:386` snapshots/sorts the memory corpus; canonical memory adapter scans entries. Unqualified definition of done NOT met. |
| Browser memory/DOM bounded | Source caps retained entries and renders a virtual slice. Runtime DOM/heap validation UNVERIFIED. |

## Disposition

BLOCKED. No evidence-backed production or ledger repair can resolve missing
trusted-base authorization or unidentified specialized producer failures.
No new tests, changed inventories, speculative scanner workarounds, or remote
mutations. Only this evidence note changes in this round.

Required next input: reviewed trusted-base authorization for the four retained
methods and candidate-specific producer logs/results. Remaining acceptance work
also needs a candidate deployment/browser run, isolated PostgreSQL validation,
and resolution of retention and non-durable initial-cost requirements without
introducing a competing authority.

The first inventory rerun rejected this note's empty inline delta syntax.
Removed it: this round adds no tests and requires no inventory delta.
Reruns passed: `uv run python scripts/check-suite-inventory.py --suite
packages/hive-conductor/backend/tests` (3310) and the same gate with
`--suite packages/maistro-core/tests` (12141). `git diff --check` passed.

Progress: checked 1, done 0, skipped 0, errors 1 (blocked). Preserve and commit
this handoff locally; do not treat its commit as integration approval.
