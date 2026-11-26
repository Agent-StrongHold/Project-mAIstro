---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 — repair job 8ad3

## Frozen scope and initial evidence

Only issue #358, branch `auto-358`, starting head
`d36d1129a75c8449152299ca2b0fb7968c662951`, supplied base
`045cfdfbe3eaa0c84493eb02754d7410b0c69378` (both verified). Worktree
started clean. Scope: existing audit implementation and adjacent tests/ADRs,
the named integration-scope and exact vulture gates, and this evidence note.
No changes to execution authorities, authorization, grants, or unrelated files.

Read driver check logs 0–7 and supplied prior result. Check-3 fails at
`test_pm_workflow_api.py:271`: external service returns an array-shaped 200
where canonical access requires 403. Check-6 requests an unregistered inventory
suite. Neither justifies weakening a test or gate.

Fresh exact vulture command (600s timeout) fails: zero unclassified findings,
but four retained `get_page` identities are unauthorized against trusted base
`8c8fc8d6706a`. The bridge already directly invokes the protocol method at
`backend/services/audit_bridge.py:186`; it is not dead code or a missing caller.
Candidate ledger banking cannot resolve trusted-base authorization. All four
identities already occur in `quality/vulture-baseline.json` at lines 1020,
1029, 1091, and 1190. No ledger amendment is warranted: removing live methods
or duplicating banked entries would not repair this gate.

Ambiguity: integration-scope is an aggregator and no candidate-specific upstream
producer logs/results were supplied. Do not fabricate successful results.
Previous directory discovery inadvertently listed sibling instruction paths;
none were opened or modified. All implementation work remains in this worktree.

## Fresh results and acceptance

Read accepted ADR-073 (canonical decision audit is admin-scoped) and ADR-062
(including the durable execution clarification). No reconciliation requires an
implementation change: preserve admin denial and the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model.

Inspected list/export/retention routes, the production bridge, both query seams,
frontend cursor/window logic, adjacent pagination tests, and the actual CI
aggregator workflow. The external check-3 failure is not evidence that this
branch's route returns an array; its checked-out route returns `AuditPage`.
External service provenance remains UNVERIFIED; no assertion weakened.

Executed with 600s gate / 1200s test timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 1; four trusted-base
  authorization failures, zero unclassified identities.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  exit 1; all nine producer results missing. This invocation diagnoses absent
  evidence, not which remote producer failed. The workflow reads check runs
  for the exact candidate SHA. Upstream failure remains UNRESOLVED; no second
  investigation or guessed CI repair.
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed. This proves the
  aggregator's local contract, not producer success.
- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2804 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 PostgreSQL cases skipped (DSN absent). Canonical SQLite
  million-row load 9.955s; maximum page-query work 3400 VM instructions.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  58 passed. Legacy SQLite million-row index migration 9.672s; first page
  0.0007s, scoped page 0.0004s; maximum measured work below 2800 VM instructions.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page | Fresh core/backend tests pass; 200-row cap, tied timestamps, duplicate correlation IDs, invalid/past-end cursors. |
| Scope/authorization before database pagination | Fresh SQLite scope/filter and deny-before-query route tests pass; PostgreSQL runtime UNVERIFIED. |
| Incremental frontend loading and virtualization | Source uses cursor loading, virtual slice, and a 500-entry retained window; browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus | Fresh filters, capped export and retention-metadata tests pass; native download avoids JS corpus accumulation. Actual purge remains absent (`audit_query.py:79`); #325 owns policy. Retention operation UNVERIFIED. |
| Representative large-dataset query/index measurement | Both real SQLite query paths measured on one million rows with deterministic work limits; PostgreSQL UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row envelope | Fresh tests pass on SQLite/memory; four PostgreSQL cases skipped. |
| Initial cost independent of total corpus | Proven for indexed SQLite after migration, not the unqualified criterion: memory fallback copies/sorts all rows (`audit_query.py:386`). |
| Bounded browser memory/DOM | Source bounds retained entries and mounted slice; runtime UNVERIFIED. |

## Disposition

BLOCKED. Only this evidence note changed; no test additions or count changes.
No actual dead identity was found, and the permitted ledger amendment was
already applied in prior work. Candidate edits cannot supply trusted-base
authorization. No grant edits, remote mutations, gate weakening, or fabricated
producer evidence. No sync conflict exists; no fetch/merge required.

Next: provide candidate-specific producer failure logs and separately authorize
the four retained identities through the trusted-base grant process. Remaining
product evidence requires browser/PostgreSQL execution and resolution of the
retention and non-durable performance limitations. This note is committed as a
blocked handoff, not a completed repair or integration approval.

Final validation: `uv run python scripts/check-suite-inventory.py --suite`
passed for `packages/hive-conductor/backend/tests` (3318) and
`packages/maistro-core/tests` (12244). `git diff --check` passed.

Progress: checked 1, done 0, skipped 0, errors 1 (blocked).
