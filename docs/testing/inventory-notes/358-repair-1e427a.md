---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — 1e427a

## Frozen scope and initial checkpoint

Only assigned issue #358, branch `auto-358`, worktree `/home/dev/Git/wt/auto-358`.
Starting HEAD verified as `351a1f984d10b7d2c1fc5fb85b03de0d1dd8720c`;
assigned base `cfb6c3b647145dfcd3ad9b7a1c38f4713d949103` resolves in the initial diff.
Initial worktree clean. Frozen repair surfaces: existing #358 audit route,
query service, bridge, core audit adapters/protocol, audit UI, adjacent audit
tests, migration 051, reviewed vulture ledger, and this note. Read-only context:
repository instructions, relevant ADRs, named CI gates and supplied job artifacts.
No re-enumeration of issues or remote mutation.

Driver logs inspected: lint/format pass; backend audit tests 76 pass; backend/core
inventory pass. Check-6 requests an unregistered inventory suite. Check-3 fails
at `test_pm_workflow_api.py:271` (external endpoint returns 200 legacy array,
expected canonical non-admin 403). Prior artifact records the same failure.
Ambiguity: external deployment revision and actual failed integration producer
logs are not supplied. Proceed by validating local production paths without
weakening security assertions or inventing CI conclusions.

## Fresh named-gate result

Exact requested Vulture command executed (exit 1): 1,347 findings versus 1,343
trusted identities. Four retained `get_page` APIs need trusted-base authorization;
the diagnostic explicitly says candidate `--update` cannot authorize them.
This is not evidence of four genuinely dead methods. No grant edit or fake
reference is justified. Integration workflow inspected: it aggregates specialized
producer conclusions, not ordinary pytest success. Actual producer failure
remains UNRESOLVED; do not infer its cause from missing local conclusions.

## Executed acceptance checkpoint

- Focused Conductor tests: 76 passed (19.91s). Million-row SQLite index
  migration 9.274s; initial/scoped pages 0.0007s/0.0004s; maximum query VM work
  <2,800 instructions. Raw output `/tmp/358-1e427a-backend.log`.
- Core audit page tests: 8 passed, 4 PostgreSQL cases skipped (no test DSN).
  Million-row SQLite load 9.009s; maximum query work 3,400 VM instructions.
  Raw output `/tmp/358-1e427a-core.log`.
- `ci_merge_group_scope.py --json` over frozen manifest surfaces requires
  docker_build, hive_e2e, postgres, wheel_imports. The named
  `check-integration-scope.py --event-name merge_group --scope-json ...`
  exits 1: six missing producer conclusions. `node --test
  tests/ci/integration-scope.test.cjs`: 12 passed; this is not producer evidence.
- ADR-073 read: canonical decision audit is admin-only. Local route denies
  before query I/O; keep the failing external assertion. ADR-037 read: events
  persist indefinitely; do not invent diagnostic-log-style audit deletion.
- `audit_bridge.py:186` invokes the four retained `get_page` implementations
  through the existing protocol; deleting them to appease Vulture would break
  production. No competing event, execution, or authorization authority added.

## Commands and final acceptance review

Executed with long timeouts:

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`
  — 76 passed.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s` — 8 passed, 4 skipped.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 1, missing trusted
  authorization. All four reviewed retained identities are already banked at
  `quality/vulture-baseline.json:1005,1014,1076,1175`; no additional ledger
  amendment is appropriate. Candidate banking cannot provide a base grant.
- `uv run python scripts/check-integration-scope.py --event-name merge_group
  --scope-json <classifier output>` — exit 1, missing docker-build,
  hive-conductor-e2e, hive-conductor-e2e-ui, postgres (pg17), postgres (pg18),
  wheel-imports. No supplied actual producer conclusions to evaluate.
- `node --test tests/ci/integration-scope.test.cjs` — 12 passed.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed, 2,852 files.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` — passed, 3,352 identities.
- Same inventory command with `--suite packages/maistro-core/tests` — passed,
  12,591 identities. No tests added or removed.
- `git diff --check` — passed.

| Acceptance criterion | Evidence / limitation |
| --- | --- |
| Bounded cursor, stable ordering, maximum page size | Executed local route and adapter tests pass (maximum 200). Driver external check-3 still fails its canonical authorization contract; no claim of deployed acceptance. |
| Authorization/scope filters before DB pagination | Executed SQLite query and HTTP denial-before-I/O tests pass. SQL places scope before limit. PostgreSQL runtime UNVERIFIED. |
| Incremental frontend loading and virtualization | `AuditLog.tsx` inspected: cursor requests, generation guard, mounted row slice. Browser runtime UNVERIFIED this round. |
| Filters, export, retention without whole-corpus browser load | Executed filter/export/retention-metadata tests pass. UI uses server filters and download link, not corpus fetch. Operational purge is not implemented (`audit_query.py:79`); ADR-037 indefinite event retention must be reconciled with #325 rather than inventing deletion. |
| Representative large dataset query/index measurement | Both actual SQLite million-row tests pass with deterministic query-work bounds recorded above. PostgreSQL envelope UNVERIFIED (skipped). |
| Concurrent inserts, cursor stability, scope isolation, maximum, empty pages | Executed Conductor and core SQLite/memory tests cover these, including tied timestamps and duplicate request IDs. PostgreSQL cases UNVERIFIED. |
| Initial page cost independent of total corpus | Durable SQLite bounds pass. Memory fallback does NOT satisfy this: `audit_query.py:402-403` copies and sorts the entire corpus on each request. |
| Browser memory/DOM rows bounded | Source retains 500 entries and mounts a viewport slice; runtime memory/DOM evidence UNVERIFIED. |

## Disposition

**BLOCKED**, not integration approval. Only this handoff note changed; all
incoming implementation and ledger entries preserved. No source repair is
justified by the named gate evidence, and no gate/assertion was weakened.
The requested previous block cannot be resolved with candidate-only changes:
trusted-base grant and candidate-specific integration producer evidence are
external prerequisites. No develop sync conflict exists in this clean starting
worktree; no fetch/merge or GitHub mutation performed.

Next: authorized owner must land the retained-API grant in the trusted base and
supply actual failed producer logs/revision-identified deployment. Then repair
actual producer failures, execute PostgreSQL/browser acceptance, and resolve the
memory-path cost and retention interpretation before declaring #358 complete.
Do not route this unchanged prerequisite failure through another speculative
source/ledger rewrite.

Progress: checked 1, done 0 repairs, skipped 0 issues, blocked 1. Commit this
note as the required local checkpoint; no closure or integration action.
