---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 repair — job 66a5

## Frozen scope

Single item: issue #358 on `auto-358`, starting head
`00346c18220d752dde61a73f8f82acd60367b886`, supplied base
`045cfdfbe3eaa0c84493eb02754d7410b0c69378` (both resolve).
Initial worktree clean. Inspect only the existing audit implementation, adjacent
ADRs/tests, and the integration-scope/vulture gates named in the assignment.
No GitHub mutations, grant changes, or unrelated repairs.

## Initial evidence

Driver check-3 fails because the external E2E target returns an old array-shaped
`/v1/audit` response (200) where the test expects canonical admin-only access
(403). This is not evidence to weaken the assertion. Checks 1/2 pass; check-4
passes 58 focused backend tests; check-6 requests an unregistered inventory
suite. Prior result reports missing integration producer evidence and four
unapproved vulture identities; these claims will be rechecked.

Ambiguity: the assignment names integration-scope without its upstream producer
failure. Inspect the gate and run its local checks; do not fabricate successful
producer results. Runtime target provenance must be established separately.

## Rechecked blockers

- Exact requested vulture command exits 1: 1365 findings, zero unclassified;
  four retained `get_page` identities fail trusted-base authorization. All four
  are already banked in `quality/vulture-baseline.json` at lines 1020, 1029,
  1091, 1190. The reachable production caller is
  `backend/services/audit_bridge.py:186`. They are not dead. Another candidate
  ledger amendment cannot authorize them; grants are outside this assignment.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`
  exits 1 with nine missing producer results. Workflow inspection confirms it
  aggregates remote candidate-specific check runs, not local unit-test results.
  No producer logs were supplied. UNRESOLVED: actual upstream failure.
- Read ADR-073: canonical decision audit must remain admin-only. Preserve the
  E2E 403 assertion rather than accepting the external service's old response.
- Requested guessed ADR-062 filename was not found; skipped that path. Resolve
  the actual filename before reading it. No unresolved ref was executed.

## Fresh validation and acceptance

Read the resolved `docs/adr/ADR-062-graph-execution-protocol.md`: its durable
execution clarification preserves `Goal -> Graph -> Run -> NodeRun -> Attempt`.
No execution or authorization authority is changed. Inspected the reachable
list/export routes, bridge, query seam, frontend, and adjacent tests.

Commands run with long timeouts (600 seconds for gates, 1200 for test battery):

- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2804 files).
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed. This validates the
  aggregator implementation, not remote producer success.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 PostgreSQL cases skipped (DSN absent). Canonical SQLite
  million-row load 8.634s, maximum measured query work 3400 VM instructions.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  58 passed. Legacy SQLite million-row index migration 11.064s, first page
  0.0008s, scoped page 0.0004s, maximum query work below 2800 VM instructions.
  Includes the external PM audit assertion against both real in-process
  production authority bindings. No audit responses mocked.

| Acceptance criterion | Evidence / remaining limitation |
| --- | --- |
| Backend bounded cursor, stable ordering, maximum page | Fresh adapter/route tests pass (200 maximum, ties, duplicate correlation IDs, invalid and past-end cursors). PostgreSQL runtime UNVERIFIED. |
| Scope/authorization before database pagination | Fresh exact-scope/filter adapter tests and deny-before-query route tests pass on SQLite. |
| Frontend incremental loading and virtualization | Source has cursor requests, virtual slice, 500-entry retained window; browser execution UNVERIFIED. |
| Filters/export/retention without browser corpus | Fresh filter/export parity and cap tests pass; frontend native download link avoids JS accumulation. Retention endpoint only reports constants; `audit_query.py:79` explicitly declares no purge. Actual retention operation UNVERIFIED (#325 policy owner). |
| Large dataset query/index measurement | Both production SQLite query paths measured on one million rows with deterministic VM bounds; PostgreSQL UNVERIFIED. |
| Concurrent inserts, stability, isolation, maximum limit, empty pages, million-row tests | Fresh focused suites pass on SQLite/memory; four PostgreSQL cases skipped. |
| Initial page cost independent of corpus | Proven for indexed SQLite after startup migration. Unqualified criterion NOT met: memory fallback copies/sorts the corpus at `audit_query.py:386`. |
| Browser memory/DOM bounded | Source bounds entries and mounted slice; runtime heap/DOM UNVERIFIED. |

## Disposition

BLOCKED; no evidence-based local code or ledger repair resolves the named gates.
All four retained methods are already banked, so no ledger amendment is needed
or valid. Changing scanner visibility or duplicating entries would evade the
trusted-base check rather than repair dead code. Integration producer failure
remains UNRESOLVED without candidate-specific logs. External E2E target
provenance remains UNVERIFIED; its array response contradicts these checked-out
routes, and is not grounds to loosen the security assertion.

Only this evidence/handoff note is changed; no tests added or counts changed.
No GitHub mutations, grant edits, gate weakening, background commands, or
unrelated work. No sync conflict exists; no fetch/merge attempted. Existing
implementation preserved. This blocked handoff will be committed locally.

Next: supply candidate-specific specialized producer logs/results and land
reviewed trusted-base authorization through the separate grant workflow.
Product acceptance additionally needs browser/PostgreSQL execution and decisions
on retention and non-durable corpus-independent page cost.

Progress: checked 1, done 0, skipped 0, errors 1 (blocked).

Final inventory validation initially rejected this note's inline empty delta;
corrected it to the required indented zero-count block. No test changes.
Reruns of `uv run python scripts/check-suite-inventory.py --suite` for
`packages/hive-conductor/backend/tests` (3318) and
`packages/maistro-core/tests` (12244) both passed. `git diff --check` passed.
