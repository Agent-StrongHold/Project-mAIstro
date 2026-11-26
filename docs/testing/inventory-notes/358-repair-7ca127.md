---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — 7ca127

## Frozen scope

Only issue #358 in `/home/dev/Git/wt/auto-358`, branch `auto-358`.
Starting HEAD `3cdb539ece60ff5bed54829f06f620ce12b2ce53` and assigned base
`45cc963267a157a9530ea4f0f688f27fdb83f3ae` both resolve. Worktree is clean.
Frozen implementation file list: the `surfaces` array in the supplied job
`7ca127b86fb345bfa7476f27546113e5/manifest.json`, plus this note. Read-only
context includes repository instructions, relevant ADRs and named CI gates.
No other issues, remote mutations, invented producer conclusions or execution
authorities. Existing committed work is preserved.

## Initial evidence and ambiguity

Driver check-3 fails at `test_pm_workflow_api.py:271`: health reports the
canonical bridge but a non-admin audit request returns HTTP 200 with a legacy
array rather than 403. Prior result reports missing integration conclusions
and trusted-base vulture authorization; these need fresh validation.
The external service revision and actual failed integration producer logs are
not supplied. Assumption: validate this checkout's production routes separately
and do not relax E2E assertions to accept the external response.

## Fresh gate evidence

The exact requested Vulture scan exits 1: 1,347 findings versus 1,343 trusted
identities. Four `get_page` methods (PgAuditLog, SqliteAuditLog, AuditLog protocol,
InMemoryAuditLog) are retained production APIs called through
`backend/services/audit_bridge.py:186`. Candidate ledger banking already exists;
the scanner explicitly requires a reviewed grant from the trusted base. No
fake caller, API deletion, or self-authorizing ledger change is justified.

Driver logs inspected: dependency sync/lint/format pass; focused backend tests
76 pass; backend/core inventories pass; check-6 fails because
`packages/hive-conductor/tests` is not a registered inventory suite.

ADR-073 requires admin scope on canonical decision audit; production
`routes/audit.py` enforces 403 before query I/O. The external response is not
reason to change that contract. ADR-037 retains domain events indefinitely;
retention policy must not invent audit deletion to satisfy diagnostic-log
retention.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 1, trusted-base
  authorization missing for four retained APIs (not missing candidate rows).
- `uv run python scripts/ci_merge_group_scope.py --json <frozen manifest
  surfaces>` computes docker_build/hive_e2e/postgres/wheel_imports=true;
  durable_events/object_storage/strike_ladder=false.
  `uv run python scripts/check-integration-scope.py --event-name merge_group
  --scope-json <computed JSON>` exits 1: six required producer results missing
  (docker-build, hive-conductor-e2e, hive-conductor-e2e-ui, postgres pg17/pg18,
  wheel-imports). This is a local evidence absence, not proof of the remote
  failure's cause. Actual remote producer logs remain UNRESOLVED.
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed; aggregator
  semantics work, but these unit tests do not replace producer conclusions.
- `uv run ruff check .`: pass. `uv run ruff format --check .`: pass,
  2,852 files already formatted.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  76 passed in 20.29s. Million-row SQLite index construction 9.511s,
  initial/scoped page 0.0007s/0.0005s, maximum query work <2,800 VM instructions.
  Includes real-route PM contract under both canonical and legacy bindings,
  scope-before-I/O, cursor continuation, bounded streaming export/projections.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: 8 passed, 4 PostgreSQL tests skipped (no configured test DSN).
  Canonical SQLite million-row load 8.490s; maximum measured query work
  3,400 VM instructions across filter combinations and deep tied cursors.

Raw focused logs: `/tmp/358-7ca127-backend.log`, `/tmp/358-7ca127-core.log`.
No successful CI conclusions have been fabricated.

- Re-ran the driver's exact external pytest command (two PM E2E files plus
  core `test_audit_pages.py`, `-q -x`): 1 failed, 7 passed, 13 skipped.
  `test_pm_workflow_api.py:271` again receives HTTP 200 instead of expected
  canonical non-admin 403. Raw log `/tmp/358-7ca127-external.log` is not
  committed because it includes audit records. Passing local production-route
  tests do not establish the external deployment's revision or security.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: pass, 3,352 identities.
  Same command for `packages/maistro-core/tests`: pass, 12,591 identities.
  `git diff --check`: pass. No tests added/removed; zero inventory deltas.

## Acceptance matrix

| Criterion | Current executed evidence / limitation |
| --- | --- |
| Backend bounded cursor, stable ordering, maximum size | Core adapter tests and Conductor HTTP tests pass; external service contract fails. |
| Authorization/scope before DB pagination | Real-route denial-before-I/O tests and SQLite filtered/scoped query tests pass. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | `AuditLog.tsx` reviewed: cursor requests and visible-row slicing; browser execution UNVERIFIED this round. |
| Filters, export, retention without whole-corpus browser loads | Filter and streaming export tests pass. Retention metadata tested; `audit_query.py:79` explicitly reports no purge. Operational retention remains owned by #325; do not claim it implemented. ADR-037 indefinite event retention takes precedence over inventing deletion. |
| Representative large-data query/index measurement | Both existing million-row SQLite tests executed; structural VM-work bounds pass. PostgreSQL million-row envelope UNVERIFIED (skipped). |
| Concurrent inserts, cursor stability, isolation, maximum, empty pages | Existing Conductor/core memory and SQLite tests pass, including tied timestamps and duplicate request IDs. |
| Initial page cost independent of corpus size | Indexed SQLite work bounds pass. Memory fallback does NOT meet this: `audit_query.py:402-403` snapshots/sorts all entries per request. |
| Bounded browser memory/DOM | Source retains at most 500 entries and slices mounted rows; browser-runtime evidence UNVERIFIED. |

## Disposition and handoff

**BLOCKED**. No production/test/gate/ledger edit is justified by the named gate
failures. The four required reviewed API identities are already present at
`quality/vulture-baseline.json:1005,1014,1076,1175`. Rewriting those identical
rows cannot authorize them; the exact scanner explicitly rejects candidate
self-authorization. Deleting used APIs or adding fake callers would be a gate
workaround, not a repair. A base grant is outside this worker's authority.

Only this evidence/handoff note changed; all incoming committed work preserved.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt model is untouched.
No remote changes, merges, pushes, or gate weakening.

Next owner actions:
1. Supply actual failed producer conclusions/logs for this candidate and point
   E2E at a freshly built, revision-identified candidate deployment. Do not
   change the expected 403 or accept legacy arrays to silence check-3.
2. Obtain trusted-base authorization for the four retained public APIs; the
   candidate ledger is already banked correctly.
3. Resolve the memory-path cost gap and retention acceptance interpretation;
   execute browser and PostgreSQL acceptance before claiming issue completion.

Checkpoint: checked 1 issue, done 0 repairs, skipped 0 issues, blocked 1.
This local documentation commit is a handoff, not integration approval.

