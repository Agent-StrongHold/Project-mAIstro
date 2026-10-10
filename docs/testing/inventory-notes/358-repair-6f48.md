---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue 358 repair — 6f48

## Frozen scope

Only issue #358, branch auto-358, starting HEAD
b185b6459296447bb0985b2a034046589a1d1713; supplied develop base
680329c960cd722034bd0053be745f3de138ba8d (both resolve). Worktree initially
clean. Files under review: audit routes/query/bridge, canonical audit paging
adapters/protocol, audit frontend, adjacent audit tests, applicable ADRs,
vulture ledger/checker and integration-scope workflow/checker. Supplied
check-0..7 logs and previous result read once. No unrelated repair scope.

## Initial evidence / assumptions

Driver check-3 receives an old unpaginated array including system actors where
canonical audit should return 403. Suspect stale external server; validate
current production seams rather than relax the assertion. Driver check-6 uses
unsupported inventory suite packages/hive-conductor/tests. Integration-scope
has no individual producer failure attached: inspect its contract and report
missing evidence honestly. Prior claims are not fresh evidence.

The read-only recursive instructions search timed out after 200 seconds;
root AGENTS.md was read. No work discarded or background process started.

## Fresh gate result

Dependency sync passed. Exact requested vulture command exited 1 (log:
/tmp/358-6f48-vulture.log). Four new get_page identities against trusted base
91996e19223d require authorization; the candidate ledger already banks them.
The method is genuinely called by audit_bridge.py:186 (outside the core scanner
roots). Removing these implementations would break canonical production reads;
adding artificial core call sites would only game the scanner. No further
ledger amendment is justified by this scan. Trusted-base grants cannot be
introduced by this lane; this is an external blocker, not a missing ledger row.

Read ADR-073: canonical decision audit must stay admin-only. Retain that rule
rather than broadening personal access to pass the external stale-service test.
Read integration-scope workflow/checker: the gate aggregates nine same-candidate
producer results, not focused pytest results. The supplied job contains no
specialized producer evidence or check-run ID to inspect. Do not invent success
results; unresolved aggregate cause must be handed back to the driver.

## Focused validation (fresh execution)

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2891 files).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed**, 23.15s (/tmp/358-6f48-backend.log). Includes the external PM
  assertion against both real production authorities through ASGI transport,
  plus canonical authorization before query. This does not certify the
  separately running external service or the full API CI producer.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py
  -x -q -s`: **45 passed, 4 skipped**, 13.07s (/tmp/358-6f48-core.log).
  PostgreSQL is not configured; no PostgreSQL result claimed.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**
  (/tmp/358-6f48-integration-unit.log).
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  **exit 1**, all nine producer results missing
  (/tmp/358-6f48-integration.log). This local invocation verifies the missing
  evidence blocker; it does NOT diagnose the remote aggregate's original
  failure. No producer success was fabricated from focused tests.
- `uv run python scripts/check-integration-scope.py --event-name merge_group
  --required-json`: passed, fail-closed scope requires the same nine producers.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
  --suite packages/maistro-core/tests`: passed; 3385, 23 and 12811 tests
  respectively, 16219 unique identities (/tmp/358-6f48-inventory.log).
  No test additions or inventory count changes.
- `git diff --check`: passed.

Guessed inspection paths backend/pyproject.toml, e2e/conftest.py,
playwright.config.ts, workflows/e2e.yml and workflows/hive-conductor.yml were
not found; skipped. No repeated exploration of those paths.

## Acceptance review

1. Bounded stable cursor pagination and maximum page size: executed route,
   convergence, adapter tests pass; ceiling is 200, ordering uses timestamp
   and unique row identity. Existing tests reject list-and-slice canonical
   reads and enforce the wire envelope.
2. Authorization/scope before database pagination: executed real SQLite
   isolation tests and pre-query authorization checks pass. ADR-073 canonical
   admin scope preserved; personal actor scope applies only to legacy data.
   PostgreSQL execution UNVERIFIED in this round.
3. Incremental loading/virtualization: inspected AuditLog.tsx, which fetches
   cursor pages, trims retained entries to 500 and renders a viewport slice.
   Fresh browser execution UNVERIFIED; prior UI claims not adopted.
4. Filters/export/retention without browser corpus loading: backend tests pass
   for filtered/scoped bounded streaming export and constant retention metadata.
   Browser export execution UNVERIFIED. Actual retention deletion is absent:
   audit_query.py:79 reports corpus_purge=none, with #325 owning policy.
5. Representative query/index measurements: real million-row legacy SQLite
   index migration 10.469s; first page 0.0011s; scoped page 0.0009s; maximum
   query work <2800 VM instructions. Canonical SQLite million-row load 10.085s,
   maximum query work 3400 VM instructions over filter shapes and deep ties.
   PostgreSQL envelope UNVERIFIED (skipped for missing DSN).
6. Concurrent inserts, cursor stability, scope isolation, maximum limits and
   empty pages: executed backend/core tests pass; million-row SQLite tests pass.
7. Corpus-independent initial page: durable SQLite request bounds pass;
   unconditional criterion NOT MET because audit_query.py:386-403 sorts the
   whole in-memory store each request. Startup migration is corpus-sized work.
8. Bounded browser memory/DOM: implementation has row-count caps; fresh browser
   proof and byte-level heap bounds UNVERIFIED. Arbitrarily large entry payloads
   are not bounded by a count-only cap.

## Handoff

BLOCKED. Only this evidence note changed; no production/test/ledger/grant or
execution-authority edits. The reviewed live identities are already banked at
quality/vulture-baseline.json:1004,1013,1075,1174. Maintainer must authorize
trusted-base debt separately or supply an approved alternative; candidate
ledger edits cannot satisfy that gate. Integration producer failure remains
UNRESOLVED without its actual check-run evidence. The driver must supply it,
point external tests at a fresh branch server, and use the supported inventory
suite key packages/hive-conductor/tests/e2e rather than its parent.

Do not repeat a no-change repair loop expecting this authorization state to
change. No develop-sync conflict was observed, so no fetch/merge was performed.
No remote mutations, services changed, or assertions/gates weakened.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; blocked 1.
Next: trusted-base authorization and actual producer diagnostics; then resolve
remaining acceptance limits before claiming full issue completion.
