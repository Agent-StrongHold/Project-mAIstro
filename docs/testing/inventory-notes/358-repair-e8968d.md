---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — e8968d

## Frozen scope

Only issue #358, assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`, clean starting HEAD `b73253b7fba0710896800380b5c7610fc572c0b9`.
Supplied base: `97c05e0f17e3ed72c82d76ed7eb0a0fe702883fb`.
Review the existing audit routes, bridge/query service, core audit adapters,
AuditLog UI, audit tests and migration; the two named CI gates and
`quality/vulture-baseline.json`; write this note. Adjacent instructions, ADRs,
CI workflow and job artifacts are read-only context. No other issue or file
repair is assigned. Existing history is preserved; no uncommitted incoming work.

Initial evidence: supplied check-3 fails on an external live endpoint returning
an old array contract and 200 instead of canonical 403. Prior result is BLOCKED,
but its gate/acceptance claims will be rerun rather than assumed.
Ambiguity: no failed integration producer log or deployed revision is supplied.
Assumption: reproduce the named gate contract locally; never invent producer
conclusions or weaken the live contract assertion. No sync conflict is present.

## Gate checkpoint

All eight driver logs inspected: dependency sync/lint/format pass; backend audit
suite 76 passed; backend/core inventories pass. Check-6 exits 2: no collection
recipe for `packages/hive-conductor/tests`. Check-3 fails as described above.

Executed the exact Vulture command with 1,200s timeout: exit 1. Trusted base
`c0441cf94b9a` contains 1,343 reviewed identities versus 1,347 findings. The four
`get_page` methods in pg_audit.py, sqlite_audit.py, protocols/memory.py and
security/sentinel/audit.py require trusted-base authorization. The diagnostic
explicitly says a candidate `--update` cannot authorize them. Review actual
callers and candidate banking before deciding any ledger amendment.

## Reproduced evidence and repair decision

- Candidate ledger already retains the four identities at lines 1005, 1014,
  1076 and 1175. `audit_bridge.py:186` invokes the protocol's `get_page` in
  production (the Hive backend sits outside the core scanner paths). Removing
  these live APIs or adding artificial callers would not be a dead-code fix.
  The permitted ledger amendment has already been made in the incoming work;
  no duplicate rows or grant edits are justified here.
- Classifier executed with the exact supplied manifest surfaces: Docker,
  Hive API/UI E2E, PostgreSQL 17/18 and wheel imports required. Running
  `check-integration-scope.py --event-name merge_group --scope-json <output>`
  exits 1: all six producer conclusions missing. This is a local evidence
  failure, not identification of the unspecified remote producer failure.
  Remote integration cause remains UNRESOLVED; do not fabricate conclusions.
- Backend audit convergence/pagination/routes/noop tests: **76 passed**, 26.07s.
  Million-row migration 12.768s; first/scoped pages 0.0010s/0.0006s;
  maximum measured query work <2,800 SQLite VM instructions.
- Core audit-page tests: **8 passed, 4 skipped**, 11.34s. Million-row SQLite
  load 9.031s; maximum query work 3,400 VM instructions. PostgreSQL tests skip
  without `MAISTRO_TEST_PG_DSN`; no PostgreSQL acceptance claim is made.
- Ruff check and format check both pass (2,852 files formatted).
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**. The gate
  implementation's tests pass; missing actual candidate evidence is not fixed.

Read ADR-073 and ADR-037: canonical decisions remain admin-only; indefinite
retention is the accepted default. The retention endpoint reports metadata,
not a purge implementation; #325 owns that separate policy lane. No new event,
authorization, execution or scheduling authority is introduced.

## Acceptance review

| Criterion | Executed evidence / remaining limitation |
| --- | --- |
| Bounded cursor, stable ordering and maximum page size | Route and adapter tests pass; max 200, tie-breaking IDs, cursor continuation and malformed cursors covered. Driver's external target still violates the contract; deployed revision unknown. |
| Authorization/scope before DB pagination | Local route denial-before-query and durable SQLite filter/scope tests pass. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | `AuditLog.tsx` source uses cursor requests and viewport slicing. Browser runtime UNVERIFIED in this round. |
| Filters, export and retention without whole-browser corpus | Filter and capped streaming export tests pass. Retention metadata endpoint tested; indefinite retention reconciled with ADR-037, purge absent under #325. Browser download runtime UNVERIFIED. |
| Representative large-dataset query/index measurements | Both million-row SQLite tests executed with deterministic work bounds above; PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million rows | Meaningful production adapter and route tests executed successfully for SQLite/memory, including threaded acknowledged writes. Four PostgreSQL cases skipped. |
| Initial cost independent of total corpus | Indexed SQLite queries proven bounded after startup migration. NOT MET for memory fallback: `audit_query.py:402-403` copies/sorts the entire store each request. |
| Bounded browser memory/DOM | Source caps retained entries at 500 and renders a viewport slice. Browser runtime UNVERIFIED. |

The passing backend tests include the PM assertion against both real local
production authority bindings. The external driver failure is not reproduced
against those local routes. Do not change the test to accept an unbounded array
or canonical non-admin access just to hide a stale/misidentified deployment.

## Commands and final handoff — BLOCKED

Validation commands (1,200s timeouts):

```
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/ci_merge_group_scope.py --json <frozen manifest surfaces>
uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classifier output>
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s
uv run ruff check .
uv run ruff format --check .
node --test tests/ci/integration-scope.test.cjs
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
git diff --check
```

Inventory checks both pass: 3,352 backend and 12,591 core identities. Diff check
passes. No test additions or inventory count changes. Changed file: this note
only. No production/ledger/gate change is justified by the named gate evidence.
No GitHub mutation, background process, discarded work or grant edit occurred.

Required next input: separately landed trusted-base authorization for the four
reviewed retained APIs; actual integration candidate producer logs/conclusions;
revision identity of the external E2E deployment. Candidate ledger edits cannot
supply these. Repeated note-only repair rounds cannot resolve those blockers.
Residual implementation risk: corpus-sized memory fallback. Residual validation
risks: PostgreSQL and browser runtime acceptance unverified.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 2 named gate
failures. Validation handoff committed locally; no integration approval claimed.
