# Issue #358 repair — bf282154

## Frozen scope

- Issue #358 only, assigned worktree `/home/dev/Git/wt/auto-358`, branch
  `auto-358`, clean starting HEAD `61f9ce048f634ab44c390b87ce6bf745fd260dc5`;
  supplied base `8c8fc8d6706a0837bd991c4e92138bf4d776ac9e` resolves.
- Inputs frozen: this job's check-0 through check-7 logs, supplied prior result
  879ceec6, existing audit route/query/bridge, canonical page adapters,
  AuditLog UI, adjacent tests, integration-scope and vulture gate definitions.
- Candidate edit scope: this note, existing audit implementation/tests only for
  demonstrated defects, and `quality/vulture-baseline.json` for an actual
  scanner bookkeeping mismatch. No grants or unrelated gate changes.
- Driver evidence: check-3 fails at `test_pm_workflow_api.py:271` against a
  live service returning an unpaginated array with 200 where the independently
  detected canonical engine requires 403. Check-6 names an unsupported suite.
  Remaining checks passed; these are not substitutes for fresh validation.
- Ambiguity: no specialized producer statuses/logs supplied for integration-scope.
  Run the real gate and record missing evidence; do not fabricate producer
  successes or weaken production authorization tests.

## Progress

Read production audit route/query/bridge, canonical SQL builder, frontend,
adjacent pagination/convergence/adapter tests, and integration gate workflow.
ADR-073 requires canonical decision audit to remain admin-only; the live-test
403 assertion must not be weakened. ADR-062's durable execution clarification
preserves `Goal -> Graph -> Run -> NodeRun -> Attempt`; no authority changes.

## Fresh commands and outcomes

All validation commands used a 1200-second timeout.

- `uv sync --locked --extra dev`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 1. 1365 findings,
  zero unclassified; four new retained `get_page` identities against trusted
  base, requiring a reviewed grant from that base. Candidate ledger already
  includes them at `quality/vulture-baseline.json:1020,1029,1091,1190`.
  Their real production caller is `backend/services/audit_bridge.py:186`.
  No dead method or bookkeeping mismatch demonstrated. Duplicating ledger
  rows, adding synthetic uses, or editing grants would not be a valid repair.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  exit 1, all nine specialized producer results missing. This is not evidence
  of which remote producer failed; that ambiguity remains UNRESOLVED without
  candidate-specific producer logs/statuses.
- `node --test tests/ci/integration-scope.test.cjs`: 8 passed.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}}'`:
  cannot connect to daemon. No shared database modified.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2804 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 PostgreSQL cases skipped (no test DSN). Million-row
  canonical SQLite load 8.199s; maximum query work 3400 VM instructions.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  58 passed. Legacy million-row index migration 9.149s; first/scoped page
  0.0007s/0.0004s; query work below 2800 VM instructions. Includes the exact PM
  audit assertion against both real in-process production authority bindings,
  without mocking audit responses. The driver's external unpaginated response
  does not match these routes; external deployment provenance UNVERIFIED.

## Acceptance evidence

| Criterion | Executed evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum page size | Focused real route/adapter tests pass: maximum 200, timestamp ties, duplicate request IDs, malformed and past-end cursors. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Canonical deny-before-query tests and exact org/actor/filter queries pass; legacy SQL scope/filter parity passes. |
| Incremental loading and virtualization | Source inspected: cursor requests, virtual slice, 500-entry retained cap. Browser execution UNVERIFIED. |
| Filters/export/retention without browser corpus | Filter/export parity and cap tests pass; UI uses native download link. Retention endpoint only reports metadata: `audit_query.py:79` explicitly says no corpus purge. Retention operation UNVERIFIED; policy owned by #325, not invented here. |
| Large-dataset query/index measurement | Both real SQLite paths measured with million-row deterministic VM-work bounds. PostgreSQL measurement UNVERIFIED (skipped). |
| Concurrent inserts, stability, scope isolation, limits, empty pages, million-row envelope tests | Focused tests pass on SQLite/memory; PostgreSQL cases skipped. |
| Corpus-independent initial page cost | Indexed SQLite request work proven after startup migration. Memory fallback snapshots/sorts entire corpus at `audit_query.py:386`; unqualified criterion NOT met. |
| Bounded browser memory/DOM | Source bounds retained entries and rendered slice. Browser runtime/heap/DOM UNVERIFIED. |

## Disposition

BLOCKED. No locally repairable cause of the named CI failures was demonstrated.
Only this evidence note changes; no tests added, no inventory-delta required.
Existing implementation and all prior work preserved. No ledger amendment is
warranted: all four reviewed live identities are already recorded exactly.
No GitHub mutations, grant edits, background commands, or fabricated statuses.
No develop-sync conflict exists, so no fetch/merge was attempted.

Next: provide candidate-specific specialized producer logs/results and reviewed
trusted-base authorization for the four retained methods. Acceptance still
requires verified candidate browser/PostgreSQL execution and resolving the
retention and non-durable initial-cost gaps. Do not retry this identical repair
brief expecting candidate ledger edits to authorize trusted-base debt.

Final validation: `uv run python scripts/check-suite-inventory.py --suite
packages/hive-conductor/backend/tests` passed (3318); the same command for
`packages/maistro-core/tests` passed (12244). `git diff --check` passed.
The driver's unsupported `packages/hive-conductor/tests` recipe was not
misrepresented as a successful gate.

Progress: checked 1, done 0, skipped 0, errors 1 (blocked). This handoff is
committed locally; it is not integration approval.
