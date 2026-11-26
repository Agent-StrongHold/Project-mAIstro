---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — job 3be527

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`bf31c03030b02238fcf428c845983e994061d106`, supplied base
`086ad770863bdc1e237a4c9bec03bf9ff076beb9`. The worktree was clean.
Review the existing audit pagination implementation and adjacent tests, supplied
check logs, integration-scope gate, and exact Vulture gate. Changes, if warranted
by actual evidence, are limited to those surfaces and this record. No unrelated
campaign items or GitHub operations.

## Initial evidence

- Driver checks 0/1/2 pass dependencies/lint/format; check 4 passes 76 audit tests.
- Driver check 3 fails `test_pm_workflow_api.py:271`: remote endpoint returns an
  old list response with >1 row for `limit=1`, instead of canonical 403.
- Check 6 names a suite without a collection recipe; this is not test failure.
- Prior result reports missing integration producer conclusions and unauthorized
  Vulture identities. These claims will be re-executed, not assumed.
- Ambiguity: the named integration-scope failure has no producer artifact in the
  provided logs. Inspect the local gate contract; do not fabricate conclusions.

## Gate checkpoint

Exact requested Vulture command executed (1,000-second timeout), exit 1:
`/tmp/358-3be527-vulture.log`. Current scan has 1,347 findings, trusted base
`c0441cf94b9a` has 1,343. Four retained `get_page` adapter/protocol identities
are already banked in the candidate ledger. They are reached through
`backend/services/audit_bridge.py:186`; removing them would break the feature.
The failure explicitly requires a separately landed trusted-base grant. No
candidate ledger duplication, fake reference, or grant edit can resolve it.

Read repository instructions, ADR-073, audit route/query/bridge, adjacent E2E,
Vulture implementation and integration-scope contract. ADR-073 requires admin
access for the canonical decision authority; do not relax the failing E2E's
403 assertion. Integration-scope consumes producer conclusions, not source scan
findings. Missing producer evidence cannot safely be converted to success.

## Acceptance checkpoint

Fresh focused backend validation: **76 passed**, 22.10s, including the actual
million-row durable SQLite test (index migration 10.010s; first/scoped page
0.0008s/0.0006s; maximum query VM instructions <2,800).
Log: `/tmp/358-3be527-backend.log`.

Source review confirms the legacy memory path snapshots and sorts the whole
corpus per request (`audit_query.py:402-403`), so corpus-independent initial page
cost is not universally met. The durable SQL path and bounded transfer contract
are tested. Browser source caps retained entries at 500 and slices the viewport;
source inspection is not browser runtime proof. Retention endpoint reports
`corpus_purge=none`; issue #325 owns purge policy.

Attempted reads of `packages/hive-conductor/playwright.config.ts` and
`.github/workflows/hive-conductor-e2e.yml`: not found; skipped. No command used
an unresolved ref or missing service ID.

## Named-gate and adapter results

- Core audit-page tests: **8 passed, 4 skipped**, 9.95s. Canonical SQLite
  million-row load 8.331s, maximum query VM work 3,400. PostgreSQL requires
  `MAISTRO_TEST_PG_DSN`; those four tests remain explicitly UNVERIFIED.
  Log: `/tmp/358-3be527-core.log`.
- Classifier run on frozen audit route/UI/core/migration paths requires
  docker_build, hive_e2e, postgres and wheel_imports. Scope saved in
  `/tmp/358-3be527-scope.json`. Integration gate exits 1: six producer results
  missing (Docker, API/UI E2E, PostgreSQL 17/18, wheels). This is a local
  missing-evidence result, not a diagnosis of the undisclosed remote failure.
- Integration aggregator's own regression tests: **12 passed**. No evidence
  warrants editing the gate; no synthetic `--result=success` supplied.
- Read ADR-037: indefinitely persisted events are the default. Reconciliation:
  do not invent a purge policy in #358; expose the existing bounds, leave any
  authorized retention-policy change to #325. An operational purge is not
  claimed as acceptance evidence.
- The executed backend suite includes
  `test_pm_audit_contract_against_each_production_authority[legacy/canonical]`:
  it runs the external PM assertion against local production routes, auth and
  real stores for both bindings. Both pass. The driver's live-service failure
  is therefore not reproduced with this worktree's routes. Target revision
  remains unknown; weakening the test to accept the old array is not a repair.

The blockers cannot be resolved by a safe candidate ledger or integration-gate
edit. Stop implementation exploration here; finalize focused validation and
commit the handoff. No new test cases or production edits are warranted by the
supplied CI evidence.

## Commands executed

All validation commands used 1,000-second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: **FAIL**, trusted-base
  authorization missing. Candidate identities already banked at
  `quality/vulture-baseline.json:1005,1014,1076,1175`; no amendment necessary.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed**.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped**.
- `uv run python scripts/ci_merge_group_scope.py --json
  packages/hive-conductor/backend/routes/audit.py
  packages/hive-conductor/frontend/src/pages/AuditLog.tsx
  packages/maistro-core/src/maistro/persistence/audit_pages.py
  alembic/versions/051_audit_cursor_indexes.py`: **PASS**.
- `uv run python scripts/check-integration-scope.py --event-name merge_group
  --scope-json "$scope"` using that classifier output: **FAIL**, six missing
  producer conclusions. No candidate-specific producer artifact was supplied.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 2,852 files.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: **PASS**, 3,352 identities.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: **PASS**, 12,591 identities.
- `git diff --check`: **PASS**.

No new tests, tests removed, ledger/grant edits, remote mutations, destructive
Git operations, or changes to execution/event/authorization authority.

## Acceptance disposition

| Criterion | Evidence / limitation |
| --- | --- |
| Bounded cursor, stable ordering, maximum page size | Executed production route/adapter tests pass; cap 200; stable tied timestamps and row IDs. Driver's external endpoint is still unresolved. |
| Authorization/scope before database pagination | SQLite scope tests and route denial-before-I/O tests pass; PostgreSQL runtime UNVERIFIED. |
| Incremental frontend loading and virtualization | Source reviewed: cursor requests and viewport slicing; browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus load | Filter and capped NDJSON export tests pass; retention metadata tested. No purge operation; ADR-037/#325 reconciliation above. Browser download behavior UNVERIFIED. |
| Representative large datasets / query indexes | Both million-row SQLite tests executed, measurements above; PostgreSQL million-row runtime UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, maximum, empty pages | Covered by executed backend and core memory/SQLite tests. Four PostgreSQL cases skipped. |
| Initial cost independent of corpus | Durable SQLite proven; legacy memory path NOT MET (full snapshot and sort). |
| Bounded browser memory/DOM | 500-entry sliding window and viewport bound in source; runtime UNVERIFIED. |

## Handoff

**BLOCKED.** Changed file: this validation/handoff note only. Existing feature
implementation is preserved, not declared merge-ready. The two named gates do
not pass. A separately landed trusted-base authorization for the four retained
APIs, and candidate-specific specialized CI producer logs/conclusions, are
required to resolve these actual gate failures. The live test target must be
revision-identified before interpreting its old response as a candidate defect.
The driver inventory command must use registered suite paths, not the parent
`packages/hive-conductor/tests` directory.

Residual product risks: memory-path corpus cost, unexecuted browser/PostgreSQL
acceptance, and retention-policy ownership as above. Another candidate ledger
rewrite or note-only round cannot remove those external blockers. Do not weaken
the security assertions or gates to obtain green checks.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 2 named-gate
failures. Next: supply trusted authorization and producer evidence, then repair
actual producer failures and complete remaining acceptance validation.

