# Issue #358 repair checkpoint (e8e30)

## Frozen scope

- Issue #358 only; supplied PR #1712 is evidence, not an integration target.
- Assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `2c278b74ade9d95d2561ecd32857d75e4ec7ae10`, supplied base
  `cd5618223cbdd9ac55d40695987e09fd8b4ef184`; both resolved locally.
- Working tree initially clean; no salvage needed.
- Repair candidates: existing audit pagination production files/tests, their
  inventory notes, and `quality/vulture-baseline.json` only for the expressly
  permitted reviewed exact-debt repair. Integration-scope tooling/workflows are
  inspection/validation only; no gate weakening or grants.
- Supplied `dispatch-context.json` and check-0 through check-7 logs inspected.
  No GitHub re-enumeration or mutations.

## Initial evidence and assumptions

- check-3 fails because a separately running HTTP server returns 200 to a test
  expecting 403. It is not yet evidence about this worktree's server.
- check-6 names an unregistered inventory suite; do not invent a suite recipe
  merely to make a driver command pass.
- Prior result reports missing integration evidence and unapproved retained
  vulture identities; reproduce the gates before changing anything.
- Acceptance includes retention, million-row performance and bounded browser
  memory, not merely passing backend unit tests.

## Gate reproduction

- Exact requested Vulture command executed: 1,342 findings vs 1,338 trusted
  base identities. Four `get_page` methods (core protocol, memory, SQLite,
  PostgreSQL adapters) require trusted-base authorization. They are live:
  `services/audit_bridge.py:185` invokes the protocol directly. Candidate
  ledger already includes them; adding duplicates is not a repair. No grant
  or scanner scope change is allowed.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`
  fails for nine missing producer results. Its workflow requires current-SHA
  specialized CI evidence; a local fabricated success map cannot supply it.
- Read ADR-068 and ADR-073: preserve Sentinel as authority and admin-only
  canonical decision audit. No execution or authorization model changes.
- Confirmed production source still declares no corpus purge and explicitly
  scans the memory fallback. These are real acceptance gaps, not permissions
  to invent a retention policy in a CI repair.

## Focused validation checkpoint

- Executed `uv run pytest` for Hive backend `test_audit_convergence.py`,
  `test_audit_pagination.py`, `test_audit_routes.py`, and
  `test_noop_route_contracts.py` with `-x -q -s`: **77 passed** in 22.81s.
  Log: `/tmp/358-e8e30-hive.log`. Actual million-row index construction
  11.236s, initial page 0.0008s, scoped page 0.0005s; maximum query work
  below 2,800 SQLite VM instructions.
- Executed core persistence `test_audit_pages.py` and workspaces
  `test_store_boundary_scope_conformance.py` with `-x -q -s`: **45 passed,
  4 skipped** in 12.48s. Log: `/tmp/358-e8e30-core.log`. Canonical SQLite
  million-row load 9.446s; maximum query work 3,400 instructions. PostgreSQL
  cases skipped because no DSN was supplied; not claimed proven.
- Candidate Vulture entries verified at lines 1001, 1010, 1072, 1171. The
  scan excludes the Hive backend caller, but widening the gate or adding dummy
  core callers would disguise evidence rather than repair code.

## Remaining validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2,926 files).
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. These prove
  the aggregator's contract, not that its required producers ran.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/tests/e2e`: passed (23 tests). This is the existing
  registered recipe; the driver's `packages/hive-conductor/tests` argument
  remains invalid. No test additions or inventory deltas in this repair.
- Fresh foreground `uv run python` probe imported production `page_entries`
  with an instrumented mapping: returning one row visited all 100 / 10,000
  entries respectively. `retention()` returned `corpus_purge: none`.
- Captured remote integration-scope evidence is successful but belongs to
  `37723b88534a36c44446f78df0a97ba3ccd4b041`, not the assigned starting head.
  It neither proves the claimed latest merge-queue failure nor resolves it.
  No current-head producer results supplied: UNRESOLVED external prerequisite.
  Two local evidence inspections suffice; no remote refresh performed.
- The failed driver PM test targets `http://localhost:8101` by default
  (`test_pm_workflow_api.py:26`). Its response is the old array shape, not
  the envelope returned by this worktree's route. A shared live target is
  not established as this build. The in-process tests above exercised both
  production bindings and passed; the external failure is not fixed or waived.

## Acceptance disposition

1. **Bounded cursor pagination / stable order / maximum size:** executed
   Hive and core tests pass on SQLite and memory; PostgreSQL runtime remains
   UNVERIFIED (four skipped cases). Source uses exact `(timestamp, id)` seeks.
2. **Authorization and scope before database pagination:** SQLite scope,
   filter and convergence tests passed, including canonical admin-only reads
   and legacy personal scopes. ADR-073 overrides any suggestion to allow
   non-admin canonical audit reads. No alternate authority introduced.
3. **Incremental loading and virtualization:** reviewed production
   `AuditLog.tsx` (100-row requests, visible slices, generation checks,
   observer attachment). Browser execution UNVERIFIED this run.
4. **Filters, export, retention without browser corpus loading:** filter and
   capped streaming export tests passed; browser uses a download link rather
   than accumulating exported data. Retention NOT MET: no purge exists.
5. **Measured representative large datasets:** both million-row SQLite tests
   passed, with deterministic work bounds and timings above. PostgreSQL
   million-row envelope UNVERIFIED.
6. **Concurrent inserts, cursor stability, isolation, limits, empty pages,
   million-row envelope tests:** 122 focused tests passed; four PostgreSQL
   cases skipped. No claim of complete all-backend coverage.
7. **Corpus-independent initial page cost:** measured SQLite path bounded;
   reachable memory fallback NOT MET (fresh counting probe above).
8. **Bounded browser memory/DOM:** source retains 500 entries and mounts only
   visible rows plus overscan; runtime UNVERIFIED. Row limits do not prove
   byte bounds on arbitrary detail payloads.

## Handoff

**BLOCKED.** Changed file: this report only. No production change is justified
by the named gate failures: the exact-debt ledger already retains all four
reviewed live APIs, and integration-scope needs genuine current-head producer
results. Adding duplicate ledger entries, dummy core callers, a local grant,
or fabricated producer success would conceal rather than resolve the evidence.
The expressly allowed ledger amendment is therefore not applicable to this
already exact candidate ledger; trusted-base authorization is still required.

Residual risks: actual retention/memory gaps, unverified browser/PostgreSQL
execution, and the unresolved external PM failure. No code, tests, grants,
quality ledgers, gate logic, or shared services changed. No pushes, GitHub
mutations, background commands, subagents, or destructive Git operations.

Progress: checked 1 issue; done 0 complete repairs; skipped 0; errors 2
reproduced gate failures. Next: obtain reviewed trusted-base authorization and
run current-candidate producers, then resolve the explicitly unmet acceptance.
This report is committed locally as the required checkpoint, not merge approval.
