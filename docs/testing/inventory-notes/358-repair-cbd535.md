---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — cbd535

## Frozen scope and initial checkpoint

Only issue #358, branch `auto-358`, worktree `/home/dev/Git/wt/auto-358`.
Starting HEAD `feada8984781ad75a3d147d1902c2cc12ba5ebf4`; supplied base
`35f2e0158a9138e592b56ed84bd08aa2e04c92a4`. Both resolved; initial tree clean.
Snapshot: supplied job check-0 through check-7 logs, prior result 9c6584,
reported integration-scope and exact-debt-ledger failures. Candidate edit files:
this note, `quality/vulture-baseline.json` if scanner evidence warrants it,
and existing #358 audit implementation/tests in the starting diff only if a
reproducible defect is found. No grant/workflow changes or unrelated repairs.

Read repository instructions and integration-scope workflow/checker. Driver
check-3 received an old list-shaped audit response from an external service;
that is not this branch's bounded contract. Do not weaken the test. Driver
check-6 passed an unregistered suite parent; correct recipe is
`packages/hive-conductor/tests/e2e`. Prior result is evidence to recheck, not
proof of success. Integration scope needs actual specialized producer outcomes;
no such outcomes were supplied. Assumption: writer repair, not verifier-only.
No conflict is present, so no develop merge is indicated.

## Named gate checkpoint

Fresh exact Vulture command exited 1 (`/tmp/358-cbd535-vulture.log`):
`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`.
1346 findings versus 1342 trusted identities (resolved base `91996e19223d`).
The four new `get_page` identities are retained production APIs in pg_audit,
sqlite_audit, protocols/memory and security/sentinel/audit. The production
bridge calls `audit_log.get_page` at audit_bridge.py:186. The candidate ledger
already banks them. The failure explicitly requires a separately landed
trusted-base grant; another candidate ledger amendment cannot authorize it.
No genuine dead identity was identified and no cosmetic API rename is justified.

`uv run python scripts/check-integration-scope.py --event-name pull_request`
exited 1: all nine specialized producer outcomes missing. This demonstrates
missing local evidence, NOT the cause of the supplied remote failure. The
workflow aggregates same-candidate producer outcomes; focused tests cannot be
substituted for those outcomes. No producer check IDs/artifacts were supplied.
Remote failure diagnosis is UNRESOLVED; no gate change is justified.

Read accepted ADR-073: canonical decision audits remain admin-scoped. The
legacy personal scope must not replace canonical authorization. No execution,
event, Goal, or authorization authority changes are planned.

## Focused validation executed

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed** (20.60s), `/tmp/358-cbd535-backend.log`.
  Real million-row legacy SQLite migration 9.630s; initial page 0.0011s;
  scoped page 0.0005s; maximum tested query work <2800 VM instructions.
  The convergence tests run the external PM assertion against this checkout's
  real routes/auth through ASGI for both legacy and canonical authorities.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: **45 passed, 4 skipped** (10.43s), `/tmp/358-cbd535-core.log`.
  Real million-row canonical SQLite load 8.334s; max query work 3400 VM
  instructions. PostgreSQL skipped without `MAISTRO_TEST_PG_DSN`; not proven.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2891 files).
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. This proves the
  aggregator's test contract, not the missing specialized producer outcomes.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
  --suite packages/maistro-core/tests`: passed (3385 / 23 / 12811 respectively;
  16219 unique identities, no duplicate evidence). No tests added or removed.
- `git diff --check`: passed.
- A grep included `packages/hive-conductor/tests/conftest.py`: not found;
  skipped. The actual PM module defines its own client fixture and target.

## Driver failure independently diagnosed

A read-only `uv run python` HTTP probe of the PM suite's resolved target
`http://localhost:8101/openapi.json` returned HTTP 200 and:

- `/v1/audit` parameters only `action`, `severity`, `actor` (no cursor/limit);
- response schema `type: array` (not this checkout's AuditPage);
- `/v1/audit/export` and `/v1/audit/retention` both absent.

Thus driver check-3 targets a server without this branch's audit contract.
Revision identity remains unknown. This is fresh runtime evidence, not an
inference from prior notes. Do not relax the tests or mutate that shared
service; rerun against an isolated server built from the candidate checkout.
Driver check-6 is a suite-selection error, independently resolved by the
registered e2e inventory command above (driver itself is outside this tree).

## Acceptance and residual gaps

1. Backend bounded cursor, stable ordering, maximum 200: focused real route
   and SQLite/memory adapter tests passed. PostgreSQL runtime UNVERIFIED.
2. Scope before pagination: real SQLite queries and canonical pre-query
   authorization tests passed. Canonical admin-only scope preserves ADR-073;
   legacy actor constraints are SQL predicates, not post-limit filtering.
3. Frontend incremental loading/virtualization: inspected AuditLog.tsx and
   existing routed component tests; 100-row requests, 500 retained entries,
   viewport slice. Fresh browser execution UNVERIFIED in this round.
4. Filters/export/retention without browser corpus: backend filter and capped
   NDJSON export tests passed; retention metadata is constant-size. Browser
   download UNVERIFIED. Actual purge is absent (`audit_query.py:79`); #325
   ownership does not make the full retention criterion satisfied.
5. Representative query/index measurement: both million-row SQLite envelopes
   executed above, including filter shapes and deep cursors. PostgreSQL million
   row envelope UNVERIFIED (skipped).
6. Concurrent inserts, cursor stability, scope isolation, maximum limit, empty
   pages: exercised by the passing backend/core suites, including acknowledged
   durable writes, tied timestamps and duplicate request IDs.
7. Corpus-independent initial cost: measured durable SQLite request work is
   bounded after startup indexing. Unconditional criterion remains unmet:
   `audit_query.py:386-403` snapshots/sorts the whole in-memory corpus per read.
8. Browser DOM/memory bounds: limits inspected, but fresh browser execution
   UNVERIFIED. Row-count caps alone do not bound arbitrary payload bytes.

## Blocked handoff

Only this evidence note changed; no code repair claimed. Candidate ledger
already contains all four live get_page identities at
`quality/vulture-baseline.json:1004,1013,1075,1174`; no missing row or genuinely
dead implementation warrants another amendment. Trusted-base authorization
requires maintainer action outside this writer lane. No grants, gates, test
assertions, external services, branches, or remote state changed.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1.
Next: supply same-candidate failing producer diagnostics for integration-scope;
land reviewed trusted-base authorization; point the driver at candidate-built
services and registered inventory recipes. Remaining browser/PostgreSQL and
retention/in-memory acceptance gaps must be addressed before MERGE-READY.
