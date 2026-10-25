---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — job 65e5da

## Frozen scope

One item: issue #358, branch auto-358, starting HEAD
81fe3b757ba22a4e37cbc2c55c182326f8a235a1, assigned base
2a24c8a82dc06ddf514404cbed622af2c751a7ea. Starting worktree clean.
Process only the named integration-scope / Vulture repair and audit acceptance
validation. Candidate edit files: this note, quality/vulture-baseline.json (only
reviewed scan findings), audit_query.py and its adjacent pagination tests if
an actual local defect is reproduced. No unrelated base differences will be
modified. Read-only evidence includes the audit routes, adapters, frontend,
ADRs, gate implementation/workflow, and supplied job logs.

## Initial evidence / assumptions

- Supplied check-3.log fails at test_pm_workflow_api.py:271: the live server
  returns an obsolete array and HTTP 200 where canonical authorization expects
  403. This is not yet evidence of a defect in this worktree's route.
- Supplied check-4.log reports 76 passes; these will be independently rerun.
- check-6.log requests an unregistered suite recipe; do not change the inventory
  gate merely to accommodate that invocation.
- Prior artifact reports missing integration producer conclusions and a trusted
  base Vulture authorization block. Reproduce rather than assuming them true.
- No conflict is present. Do not merge unrelated develop changes speculatively.

## Named gate checkpoint

The exact requested Vulture command exits 1: 1,346 findings versus 1,342
trusted-base identities (resolved base 29af8200e4a8). All four new identities
are get_page on the core protocol and its PostgreSQL/SQLite/memory adapters.
The actual production bridge calls audit_log.get_page directly at line 186;
these are retained APIs, not dead code. They are already in the candidate ledger.
No duplicate banking or fake call sites will be added. The failure explicitly
requires trusted-base authorization; a candidate ledger edit cannot supply it.

The integration gate aggregates nine remote specialized producer conclusions.
The supplied logs contain none of those conclusions or the failed merge-group
candidate ID. Remote root cause is UNRESOLVED, not a basis for a workflow edit.
No conflicting merge state exists.

An attempted ADR-037 filename was not found; skipped. Resolved filenames from
the local ADR directory will be used instead.

## Acceptance checkpoint

- Independently reran the four focused Conductor backend audit suites: 76 passed
  in 24.72s. Million-row index migration 12.371s; initial page 0.0008s; scoped
  page 0.0005s; maximum query work <2,800 SQLite VM instructions.
- `check-integration-scope.py --event-name pull_request` exits 1, all nine
  producer conclusions missing. This local missing-evidence result is not a
  diagnosis of the remote merge-group producer failure.
- ADR-037 retains events indefinitely; #325 owns purge policy. ADR-073 requires
  canonical decision audit to be admin-scoped. Neither contract will be relaxed.
- Source confirms that the reachable memory fallback snapshots/sorts the full
  corpus at audit_query.py:402. The unconditional initial-cost criterion is NOT
  MET, despite durable-query bounds. A repair needs write-maintained indexing
  across all mutation paths, not a stale-cache heuristic or a cosmetic read edit.
- Frontend retains at most 500 entries, virtualizes viewport rows, guards stale
  responses and uses native streamed export. Runtime browser evidence remains
  UNVERIFIED; source review alone is insufficient.
- PostgreSQL containers exist but belong to other lanes. Do not run the fixture
  (which truncates shared tables) against any of their databases. No test DSN
  has been supplied for this worktree.
- Guessed root-level Conductor Playwright/package paths were not found; skipped.
  No command was run against those missing paths.

## Final validation checkpoint

- Core audit adapter suite: 8 passed, 4 PostgreSQL cases skipped (no DSN).
  Real million-row SQLite load 7.830s; maximum query VM work 3,400 instructions.
- Ruff check and format pass (2,886 files).
- First inventory invocation rejected this note's inline empty inventory-delta
  block. Corrected to the required indented per-suite zero counts; rerun passed:
  backend 3,369; e2e 23; core 12,761. Whitespace check passed.
- Reviewed tests exercise real SQLite stores and bound production ASGI routes,
  including authorization-before-query tripwires, concurrent writes, key ties,
  filters, caps, scope isolation, empty pages, export and retention metadata.
  The externally failing PM audit assertion also executes against both local
  production authority bindings in test_audit_convergence.py and passes.

- Read-only httpx probe using the e2e fixture's HIVE_BASE_URL/default: HTTP 200
  OpenAPI describes GET /v1/audit as an array with only action/severity/actor
  parameters. This is not the local limit/cursor/page contract. No setup/login
  or shared deployment mutation was performed. External e2e failure is real,
  but editing local tests to accept the old server would hide the regression.

## Commands and outcomes

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
  FAIL: trusted-base authorization required for four already-banked APIs
uv run python scripts/check-integration-scope.py --event-name pull_request
  FAIL: actual producer conclusions unavailable; no fabricated --result values
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
  PASS: 76
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s
  PASS: 8; SKIP: 4 PostgreSQL cases
uv run ruff check .
uv run ruff format --check .
  PASS
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests
  PASS after correcting this note's front matter
uv run python (read-only httpx OpenAPI probe described above)
  PASS: external deployment mismatch confirmed
git diff --check
  PASS
```

Commands used 1,000–1,200 second timeouts. Detailed local run output is in
/tmp/358-65e5da-{vulture,backend,core}.log (ephemeral); results are recorded here.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded cursors, stable ordering, maximum page | Local routes and SQLite/memory adapter tests pass; external server contract mismatch persists. |
| Scope filters before database pagination | Real SQLite tests and SQL review pass; PostgreSQL runtime UNVERIFIED. |
| Incremental frontend and virtualization | Source reviewed; browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus loading | Backend tests pass; browser export UNVERIFIED. ADR-037 indefinite retention preserved; no purge claim. |
| Representative query/index measurements | Two real million-row SQLite envelopes pass with deterministic work bounds above; PostgreSQL UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope tests | Focused suites pass; PostgreSQL cases skipped. |
| Initial cost independent of corpus | NOT MET by reachable memory fallback, audit_query.py:402. Durable SQLite bound measured. |
| Bounded browser memory/DOM | 500-entry cap and viewport slicing present; runtime UNVERIFIED. |

Verdict: **BLOCKED**. Only this evidence note changed. No scanner gaming,
duplicate ledger rows, grant edits, workflow weakening, or remote mutations.
The candidate ledger already contains the four retained identities at lines
1004/1013/1075/1174; amending it again cannot repair trusted-base authorization.

Progress: checked 1 issue, done 0 implementation repairs, skipped 0 issues,
errors 2 unresolved named gates. Next: supply the actual failed integration
producer logs/candidate ID and trusted-base authorization through the separate
governance lane; validate an isolated candidate-matching API/browser deployment
and migrated PostgreSQL database. The unconditional memory-fallback performance
requirement needs a focused write-maintained index design spanning mutation
paths. Do not repeat an evidence-only repair expecting those external blockers
to disappear. Commit this handoff locally; it is not integration approval.
