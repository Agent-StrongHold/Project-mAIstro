---
inventory-delta:
  packages/hive-conductor/backend/tests: 3
  packages/maistro-core/tests: 12
  packages/hive-conductor/tests/e2e: 0
---

# Issue 358 repair — d3c86c

## Frozen scope

- Only issue #358, branch `auto-358`, starting head
  `c0dc073625f776fa9656183783e8d1c66fa7b15b`, assigned base
  `e8793477ec4c68cdfe37dd89f6081167801f07d1`.
- Investigate the audit route/query/store/UI and adjacent tests, the failing live
  audit contract test, integration-scope gate, and explicitly requested vulture
  ledger gate. No unrelated repair, grant edits, or GitHub mutations.
- Existing tree clean; prior implementation retained.

## Initial evidence

- Driver check-3: `TestAuditTrail.test_audit_log_has_entries` received a list
  rather than the expected paginated response envelope.
- Driver check-4: 53 tests passed (not independently accepted yet).
- Driver check-6: `packages/hive-conductor/tests` has no inventory collection
  recipe; this is an invalid gate invocation, not evidence of inventory drift.
- Ambiguity: live tests may target another checkout. Inspect configured service
  target before interpreting a live failure as this checkout's production code.

## Validation and disposition

Named vulture gate PASS: 1,359 reviewed identities / 1,359 findings; no
ledger amendment justified. The real production defect is confirmed in code:
`routes/audit.py` returns the canonical core list unchanged, incompatible with
the frontend envelope. This is not merely a foreign-service test failure.
ADR-073 requires canonical decision audit to remain admin-only. ADR-082226-5104
requires preserving the core PostgreSQL authority; paginating a legacy replica
or slicing a 10,000-row core result is not an acceptable repair.

Integration-scope is an evidence aggregator, not a test suite. Supplied logs
contain no named failing producer conclusion; do not fabricate success results.
Core adapters inspected: PgAuditLog, SqliteAuditLog, InMemoryAuditLog and the
AuditLog protocol expose only get_entries; no cursor query exists. Repair files
are now fixed: those three adapters, protocols/memory.py, a shared
persistence/audit_pages.py, Alembic 051_audit_cursor_indexes.py, audit_bridge.py,
routes/audit.py, test_audit_convergence.py, new core test_audit_pages.py, and this
note (plus the explicitly permitted vulture ledger only if new findings arise).
Use the existing immutable audit row primary key to break timestamp ties;
request_id is correlation, not unique identity. Preserve exact org scope before
LIMIT. Keep canonical decision access admin-only before querying. Do not invent
retention/purge policy; report it unverified under #325.

## Implementation checkpoint

Canonical core get_page implemented on the three existing adapters; PG migration
051 creates eight filter-shape indexes, SQLite builds them during ensure_schema.
Conductor list/export now use core pages, enforce admin before any store read,
and expose stable core row IDs rather than random fallback request IDs.
Existing unbounded get_entries remains for other callers, not this HTTP path.

- Canonical convergence suite: 10 passed, including three new cases (two
  authorization parameterizations and canonical cursor/export roundtrip).
- New million-row test initially FAILED: SQLite's tuple predicate seeks only
  timestamp for filtered indexes, scanning deep timestamp ties. Fixed via two
  disjoint limited seeks (equal timestamp/lower ID and older timestamps).
  This is a measured query repair, not a relaxed performance assertion.
- `uv run alembic heads`: 051, single head.
- Docker unavailable: cannot connect to unix:///var/run/docker.sock. Real PG
  and isolated browser/API Compose validation currently blocked; do not claim
  mock SQL checks prove PostgreSQL execution.

## Validation checkpoint 2

- Core focused audit suites: 43 passed / 4 skipped (real PG not configured).
  Million canonical SQLite rows loaded with indexes in 8.095s; all 16 first/deep
  filter-shape queries used at most 3,400 VM instructions (hard abort at 10,100).
- Hive focused audit suites: 56 passed; legacy million-row query also measured
  (<2,800 VM instructions); canonical route/authorization/export tests pass.
- Core changed-module mypy: PASS, five source files.
- Full-tree Ruff lint and format: PASS (2,769 formatted files).
- Suite inventory: PASS, core 12,080 / backend 3,273 / e2e 23 (before adding
  one optional real-PG million-row measurement case; final counts below).
- Principal identity gate: PASS, four tolerated / four current, none new.
- Integration-scope: FAIL, all nine producer results absent from this job;
  no result fabricated and no gate weakened.
- Vulture found four new get_page identities. Reviewed runtime consumer is
  Hive's page_core_audit_entries -> Container.audit_log.get_page; Hive backend
  lies outside the gate's packages/*/src scan. Retained all three adapters and
  the protocol declaration, banking exactly those four identities per the
  explicit CI-repair allowance. No duplicates removed, no grant edits.
  **Banking does not authorize**: trusted-base ratchet still requires a separate
  reviewed authorization; do not claim this gate passes.
- Adjacent failing e2e audit case must use admin credentials for core decision
  audit (ADR-073), not personal legacy-scope expectations. Updated that existing
  case to assert PM list/export denial plus admin cursor traversal. This is the
  same originally frozen failing test file; no new e2e test node added.

## Finalization checkpoint

No new items started. Broader core persistence + Sentinel suite: **597 passed,
178 skipped** (PostgreSQL-dependent lanes unavailable), log `repair-core.log`
in this job directory. Added optional real-PG million-row EXPLAIN/BUFFERS test;
it remains skipped locally, not acceptance evidence.

Radon gate identified one new block introduced here (memory get_page, C14)
and two pre-existing blocks (container._reconcile_unreconciled_terminal_attempts,
canonical_store._has_stalled_active_frontier). Refactored this lane's filter
predicate into a named helper; no radon ledger edit or unrelated repair.

Two runtime-only attempts to replace the original GET handler for regression
proof did not affect the exercised route (both tests passed). Mark that
experiment UNRESOLVED, not a proven regression failure; stop investigating it.
The million-row canonical test DID fail against the first tuple-seek
implementation and pass after the measured split-seek repair. Source-backed
route tests also prohibit calling unbounded get_entries while listing/exporting.

Existing UI inspected: requests 100-row pages, retains at most 500 entries,
renders a viewport slice with overscan, streams export via download href. No
browser execution this round: Docker is unavailable. Entry-count bounds are
not a byte-level heap bound (individual detail payload size is not capped).

Outstanding acceptance risks: retention/purge remains absent (#325); retention
metadata and legacy detail/create routes are not fully converged to core;
memory adapter query CPU remains O(n); PostgreSQL migration/query behavior and
browser envelope integration await live validation. No claim of complete #358
acceptance or integration approval.

## Final executed evidence

Logs: `/home/dev/maistro/jobs/d3c86c3ed4384973821c9ffb347bde2c/repair-*.log`.

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_audit_convergence.py -x -q -s` | 56 passed, 19.46s |
| `uv run pytest packages/maistro-core/tests/persistence packages/maistro-core/tests/security/sentinel -x -q` | 597 passed, 178 skipped, 12.38s |
| `uv run mypy` on the five changed core source modules, `--follow-imports=silent` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e` | PASS: 3273 / 12081 / 23 |
| `uv run python scripts/check-principal-identity.py` | PASS: no new violations |
| `uv run alembic heads` | PASS: single head 051 |
| `DATABASE_URL=postgresql://offline:offline@127.0.0.1/offline uv run alembic upgrade 050:051 --sql` | PASS: renders all eight indexes, no DB connection attempted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | FAIL: 1363 actual, candidate ledger exact; four get_page identities lack trusted-base authorization |
| `uv run python scripts/check-radon-baseline.py` | FAIL: two pre-existing blocks; this repair adds no remaining C-or-worse block |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` | FAIL: nine required producer conclusions missing |
| `git diff --check` | PASS |

First offline migration attempt without DATABASE_URL failed configuration
validation; explicit dummy offline URL fixed the invocation, not application code.
No migration was applied to a live database. The revised external API e2e test
and browser suite remain unexecuted here; do not reuse the foreign :8101 target
as evidence for this checkout.

## Acceptance matrix

1. Bounded cursor pages / stable ordering / maximum: canonical SQLite and memory
   conformance executed (immutable IDs, duplicate/empty request IDs, timestamp
   ties, 200 cap). Core HTTP returns the envelope. PostgreSQL execution UNVERIFIED.
2. Scope/authorization before pagination: exact-org and combined-filter SQLite
   queries executed; non-admin core list/export rejected before any store read.
   PostgreSQL predicates asserted structurally; live execution UNVERIFIED.
3. Incremental frontend + virtualization: existing code inspected; browser
   execution UNVERIFIED this round. No new scheduler, Goal/event authority, or
   alternate principal path introduced.
4. Filters/export: canonical route tests execute filtered NDJSON export from the
   same store and a reduced cap; prohibit unbounded get_entries calls. Retention
   still reports no purge, so this criterion is NOT complete.
5. Query/index measurement: canonical SQLite million-row / 16 query shapes,
   <=3400 VM instructions. PostgreSQL EXPLAIN/BUFFERS case added but skipped;
   its migration and performance envelope remain UNVERIFIED on a live DB.
6. Concurrency, stability, scope isolation, max, empty, million-row tests:
   executed on SQLite/memory as applicable; real PostgreSQL cases skipped.
7. Initial page cost independent of corpus: bounded SQLite query work measured;
   memory backend remains a linear scan, so universal definition of done fails.
8. Browser memory/DOM bound: <=500 retained entries and windowed rendering in
   source; browser execution and byte-level heap profiling UNVERIFIED.

## Changed files and handoff

- Core: `persistence/audit_pages.py`, `persistence/{pg,sqlite}_audit.py`,
  `security/sentinel/audit.py`, `protocols/memory.py`, and
  `tests/persistence/test_audit_pages.py`.
- Migration: `alembic/versions/051_audit_cursor_indexes.py`.
- Hive: `backend/routes/audit.py`, `backend/services/audit_bridge.py`,
  `backend/tests/test_audit_convergence.py`, `tests/e2e/test_pm_workflow_api.py`.
- Reviewed ledger: `quality/vulture-baseline.json` (+4 identities only).
- This inventory/handoff note (+12 core tests, +3 backend tests, no e2e delta).

Verdict: NEEDS-REPAIR. Local commit is a partial writer handoff, not approval.
Next: independently authorize retained API debt through the existing grant
process; supply actual integration producer evidence; run migrated PG and
browser/API tests; resolve retention and remaining read-surface convergence.
Do not weaken gates or infer green results from banked ledger rows.

Progress: checked=1, done=0 acceptance-complete, skipped=0, errors=3 failed
gates. No remote mutation, no issue closure, no discarded work.
