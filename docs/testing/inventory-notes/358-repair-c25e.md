---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — c25e

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`f98a49e11721e1343c22bb367fba4df263c29129`, base
`45cc963267a157a9530ea4f0f688f27fdb83f3ae`. Clean worktree at entry.
Files in scope: existing audit pagination implementation and adjacent tests,
Conductor E2E harness, named integration-scope/vulture gates, this evidence note,
and (only if actual scan requires) `quality/vulture-baseline.json`.
No other issues, remote mutations, gate weakening, or new execution authority.

## Initial evidence

Driver logs in `/home/dev/maistro/jobs/c25e6ce2172d43beb30512a683df4b03`:
- check-0/1/2: dependency sync, lint, format pass.
- check-3: external service `/v1/audit?limit=1` returns a legacy unbounded
  array, HTTP 200 instead of expected canonical non-admin 403 (test line 271).
- check-4: 76 focused backend tests pass.
- check-5/7: backend/core inventory pass.
- check-6: `packages/hive-conductor/tests` is not a registered inventory suite.

Prior result was BLOCKED on absent integration producer conclusions, vulture
trusted-base authorization, external stale service, and memory fallback cost.
These are leads, not accepted current verification.

Ambiguity: no actual integration-scope producer failure log was supplied.
Assumption: inspect the named gate and execute its locally available checks;
do not fabricate successful producer conclusions. External service provenance
is unknown; validate the worktree independently rather than relax assertions.

## Executed gate evidence

- Exact requested Vulture command exits 1: 1,347 findings vs trusted-base
  1,343. The four `AuditLog.get_page` definitions are retained APIs consumed by
  `backend/services/audit_bridge.py:186` outside the `packages/*/src` scan.
  They are already banked in the candidate ledger; the failure explicitly
  requires trusted-base authorization. Removing working pagination APIs or
  adding dummy internal callers would not be a genuine dead-code repair.
  No ledger change can supply that missing base authorization.
- ADR-073 (Accepted) requires canonical decision-audit admin scope. Existing
  route authorization enforces this before reads. Do not change 403 expectations
  to accommodate the external server's old array response.
- Computed scope from the resolved assigned base with
  `git diff --name-only 45cc963267a157a9530ea4f0f688f27fdb83f3ae...HEAD` and
  `uv run python scripts/ci_merge_group_scope.py --json <changed paths>`.
  `uv run python scripts/check-integration-scope.py --event-name merge_group
  --scope-json <computed scope>` exits 1: missing docker-build,
  hive-conductor-e2e, hive-conductor-e2e-ui, postgres (pg17), postgres (pg18),
  wheel-imports. Unlike the prior note's fail-closed nine-check invocation,
  the assigned base's exact diff requires six conclusions. None were fabricated.
  The supplied job logs contain no producer conclusions and do not identify
  a failed GitHub check-run ID; remote failure root cause remains UNRESOLVED.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed. This exercises
  the aggregator, not the specialized producers, and cannot approve integration.
- `uv run ruff check .`: pass. `uv run ruff format --check .`: pass (2,852 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 skipped (PostgreSQL has no configured test DSN).
  Canonical SQLite: 1,000,000 rows loaded in 10.429s; maximum measured query
  work 3,400 VM instructions over all filter shapes and initial/deep cursors.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  76 passed. Legacy SQLite million-row index build 10.573s, initial page
  0.0010s, scoped page 0.0007s, max measured work <2,800 VM instructions.
  Includes the external PM audit assertion against this checkout's real routes,
  auth and both legacy/canonical bindings, not a mocked audit response.
- Re-ran the exact driver E2E command with `uv run pytest`, the two PM files
  and core audit-pages file, `-q -x`: 1 failed, 7 passed, 13 skipped. Failure
  reproduced at `test_pm_workflow_api.py:271`: the external service still
  returns HTTP 200 / a legacy array for a canonical non-admin. Local route
  tests pass; the external deployment's actual revision remains UNVERIFIED.
  Raw log: `/tmp/358-c25e-external-e2e.log` (not committed; contains audit data).
- Initial inventory runs caught this new note's unsupported inline empty delta;
  corrected to explicit indented zero deltas. No tests added or removed.
  Re-ran `uv run python scripts/check-suite-inventory.py --suite` for each
  registered suite: backend passes at 3,352, core passes at 12,591.
  `git diff --check` passes.

## Acceptance and remaining blockers

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Bounded cursor, stable order, maximum page | Core adapter and Conductor HTTP tests pass locally; external E2E fails. |
| Authorization/scope before DB pagination | SQLite scope/filter-shape tests and real-route authorization-before-I/O tests pass; PostgreSQL runtime UNVERIFIED. |
| Frontend incremental loading and virtualization | Reviewed `AuditLog.tsx`: cursor continuation, window slicing, 500-row retained cap. Browser execution UNVERIFIED this round. |
| Filters, export, retention without whole-corpus browser reads | Filter/export/retention-metadata tests pass. Export streams bounded pages. Operational purge is not implemented (`audit_query.py:79`), belongs to #325; no new purge mechanism invented. ADR-037 also distinguishes indefinitely retained events from diagnostic logs. |
| Representative query/index measurement | Both existing SQLite million-row tests executed, measurements above. PostgreSQL envelope UNVERIFIED (skipped). |
| Concurrent inserts, cursor stability, isolation, maximum, empty pages | Existing SQLite/memory adapter tests and Conductor tests executed successfully. |
| Corpus-independent initial page cost | Proven query-work bound for indexed SQLite paths; NOT MET by memory fallback (`audit_query.py:402-403` copies/sorts corpus; canonical memory adapter also scans). |
| Bounded browser memory/DOM | Source cap/window reviewed, but browser-runtime evidence UNVERIFIED. |

No production/test/gate/ledger edits are justified by the named gate failures:
the candidate ledger already retains exactly the four reviewed public APIs;
it cannot authorize itself. No conflicting/uncommitted incoming work existed.
Only this evidence/handoff note changes in this round. The canonical
Goal -> Graph -> Run -> NodeRun -> Attempt authority is untouched.

Disposition: **BLOCKED**, not a repair-complete or integration approval claim.
Next owner actions: supply the actual failed specialized check-run logs for
this candidate; run E2E against a freshly built candidate deployment; obtain
trusted-base review/authorization for the four already-banked API identities.
Do not repeat candidate ledger edits expecting them to authorize new debt.
Also resolve the memory-backend acceptance gap and execute browser/PostgreSQL
acceptance before claiming #358 complete. No remote changes were made.

Checkpoint: checked 1 issue, completed 0 repairs, skipped 0 issues, blocked 1.
