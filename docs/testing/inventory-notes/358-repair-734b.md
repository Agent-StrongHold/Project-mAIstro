# #358 repair checkpoint — job 734b

## Frozen scope

One item: issue #358, branch auto-358, starting HEAD
`eae779e3c4050702d2c24e6b706903fae02f6623`.
Inspect the supplied job check logs, audit routes/query/store/UI and adjacent
pagination/E2E tests, relevant ADRs, integration-scope workflow and vulture gate.
Candidate edits are limited to evidenced #358 test/implementation defects, this
note, and reviewed vulture identities if the requested gate reports any.
No other issues or historical repair-note lists will be processed.

Initial status clean. Supplied base `c0441cf94b9a8e58517da0f4159070b97ea6a706`
resolves but `git merge-base HEAD <base>` returned no common ancestor; do not
interpret the two-tree diff as this repair's changes or merge unrelated histories.
Assumption: validate the assigned HEAD locally, not the independently running
server used by the driver. No develop sync conflict is present.

Driver evidence: check-3 failed at test_pm_workflow_api.py:271: live canonical
probe followed by legacy audit array/HTTP 200 instead of scoped denial/403.
check-6 reports no collection recipe for packages/hive-conductor/tests.
Other supplied checks reported success; fresh validation pending.

Fresh `uv sync --locked --extra dev` passed. Requested Vulture command failed:
1349 findings, zero unclassified; candidate ledger matches, but four retained
`get_page` identities lack trusted-base authorization (pg_audit.py:49,
sqlite_audit.py:96, protocols/memory.py:404, sentinel/audit.py:42).
The gate explicitly says candidate edits cannot authorize them. Do not add
fake callers or remove public bounded-read APIs merely to silence the scanner.

Read ADR-073 and ADR-081226-a66b: canonical Sentinel decisions remain
admin-only; no competing audit/execution authority is permitted. Source review
confirms the legacy in-memory query sorts the corpus per request, while durable
queries use bounded indexed seeks. Retention declares no purge job (#325).
Integration-scope consumes remote specialized-job conclusions, not ordinary
pytest results; no such conclusions are supplied in this job's artifacts.

## Executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2861 files.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  76 passed (20.78s).
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`:
  8 passed, 4 PostgreSQL legs skipped (no MAISTRO_TEST_PG_DSN).
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  failed closed, all nine specialized conclusions missing. This is **not** a
  reproduction of the remote producer failure; the underlying remote failed
  job cannot be identified from the supplied integration-scope status alone.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed.

Measured current SQLite million-row envelope: legacy index migration 10.270s;
first page 0.0008s; scoped page 0.0004s; maximum VM work <2800 instructions.
Canonical SQLite load 7.972s; maximum query VM work 3400 instructions.
Logs are `/tmp/358-734b-{backend,core,integration,integration-selftest,vulture}.log`.

UNRESOLVED: trusted-base authorization and remote integration producer evidence.
No gate/ledger edits are justified: all four retained identities are already in
the candidate ledger, and Conductor's bridge really calls `audit_log.get_page`
(backend/services/audit_bridge.py:186). These are public APIs outside the
scanner's closed source-only call graph, not dead methods.

Final focused rechecks:

- Exact driver pytest command (PM agent/workflow API plus core audit pages):
  1 failed, 7 passed, 13 skipped. Failure reproduced at
  `packages/hive-conductor/tests/e2e/test_pm_workflow_api.py:271`: the external
  service on the default localhost:8101 returns a legacy array with HTTP 200
  where the canonical admin-only contract requires HTTP 403. The local route
  raises 403 before I/O (`routes/audit.py`, `_authorized_core_audit`), and the
  in-process convergence tests passed. Do not relax the assertion to accept
  the stale/unscoped external response. Log: `/tmp/358-734b-driver-recheck.log`.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`:
  passed (3352).
- Same gate with `--suite packages/maistro-core/tests`: passed (12486).
- Same gate with `--suite packages/hive-conductor/tests`: exit 2, no collection
  recipe. This is an unsupported driver suite argument, not inventory drift.
- `git diff --check`: passed.

## Acceptance disposition

| Criterion | Evidence / limitation |
| --- | --- |
| Bounded cursor, stable order, maximum page size | Local route and canonical adapter tests passed; external service fails the contract. |
| Scope before database pagination | SQL/filter/isolation tests passed; ADR-073 admin denial tested locally. |
| Incremental frontend and virtualization | Source has cursor loading, 500 retained entries, viewport slicing; browser runtime UNVERIFIED this round. |
| Filters/export/retention without browser corpus load | Filter/scoped/capped NDJSON and retention-metadata tests passed. Purge not implemented (`audit_query.py:79`); #325 owns policy. Operational retention UNVERIFIED. |
| Representative large-dataset query/index measurements | Both SQLite million-row tests executed with measured VM bounds above. PostgreSQL UNVERIFIED (4 skipped legs). |
| Concurrent inserts, cursor stability, scope, limit, empty pages | Existing focused tests passed for SQLite and memory; PostgreSQL UNVERIFIED. |
| Initial page cost independent of corpus | Proven by durable SQLite VM bounds; NOT MET for memory (`audit_query.py:402-403` snapshots and sorts the corpus). |
| Bounded browser memory/DOM | Source-reviewed bound; runtime UNVERIFIED. |

## Handoff — BLOCKED, not repaired

Only this note changed; no production/test/gate/ledger edits, no test inventory
delta. Candidate ledger already retains the reviewed identities at lines
1005, 1014, 1076, 1175. An authorized maintainer must land trusted-base approval
before the Vulture gate can pass; this lane must not forge that approval.
Supply the actual failed integration producer log/conclusions, and run the E2E
suite against an isolated deployment built from this branch rather than the
existing localhost service. No remote mutations were performed.

Progress: checked 1 issue, done 0, skipped 0, blocked 1. No further historical
repair notes or issues investigated. Remaining product gaps are recorded above;
this validation-only commit is not an integration approval or a gate repair.


