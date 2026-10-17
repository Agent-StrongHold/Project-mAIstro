---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — c007d0fd

## Frozen scope

One assigned item: issue #358, branch `auto-358`, starting HEAD
`d6c8cbc8cfa506285928031e6872ad582661e33e`, supplied base
`e067b7b0aca01b578f0bf2446dc0864fc4d88d15`. Both refs resolve; initial
worktree clean. No remote mutations or scope expansion.

Files to inspect: repository instructions; ADR-037 and ADR-073; named CI
workflow/gates and Vulture ledger; audit routes/query/bridge, persistence
adapters/protocol, AuditLog frontend, and their existing tests. Permitted
repair files are those audit implementation/test files, the explicitly
permitted Vulture ledger, and this note. Do not change CI authorization or
integration producer requirements.

## Initial evidence

Read job `c007d0fd73ac4c27bdb4324cb6a94e02` check-0 through check-7 logs
and supplied prior result. Driver lint/format pass; audit backend tests
76 passed. Driver live API test fails at
`test_pm_workflow_api.py:271`: expected canonical 403, received 200 and
an unpaginated array. Driver inventory target `packages/hive-conductor/tests`
has no collection recipe. Prior claims are not acceptance evidence for this
round.

Ambiguity: live target revision is not identified by the logs. Assume its
response is real evidence of an incompatible target, not permission to relax
the contract. Named gate failures will be reproduced before edits.

## Gate checkpoint

Exact Vulture command executed (1,200s timeout): exit 1; trusted base
`c0441cf94b9a` has 1,343 identities versus 1,347 findings. The four `get_page`
methods require trusted-base authorization. The command explicitly states
that candidate ledger updates cannot authorize them. No grant edit or artificial
caller will be used to evade this gate.

Read accepted ADR-037 and ADR-073: indefinite audit event retention is the
default; canonical decision audit remains admin-scoped. Preserve both contracts.
Source confirms a remaining implementation limitation at
`backend/services/audit_query.py:402`: memory fallback snapshots and sorts the
entire corpus per page. Durable SQL uses bounded indexed seeks; these are not
equivalent performance guarantees. The canonical in-memory adapter also scans
all entries (`security/sentinel/audit.py:54-66`), although it bounds result memory.

Classifier ran against the frozen manifest surfaces. Required legs: PostgreSQL,
Hive E2E, wheel imports and Docker build. Running the integration-scope gate with
that classifier output and no fabricated results exits 1: six missing producer
conclusions. This proves local evidence is incomplete; it does NOT reproduce or
identify the unspecified remote producer failure. Remote failure: UNRESOLVED.

Candidate Vulture rows already exist at ledger lines 1005, 1014, 1076, 1175;
production caller `backend/services/audit_bridge.py:186` invokes `get_page` on
the bound AuditLog protocol. These APIs are retained, not genuinely dead. The
explicitly permitted candidate ledger amendment is already in the starting
commit history. Duplicating rows, deleting live methods, or adding artificial
core callers is not a justified repair. The remaining gate needs a separately
landed trusted-base authorization, outside this lane's permissions.

Frontend source review: pages are requested incrementally, retained entries are
capped at 500, a viewport slice is rendered, export is a native download link.
No browser execution has established those runtime properties this round.

## Focused validation executed

All commands below used 1,200s timeouts. No test or production edits made.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 1, trusted-base authorization failure described above.
- `uv run python scripts/ci_merge_group_scope.py --json <frozen manifest surfaces>`: exit 0, scope recorded above.
- `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classifier output>`: exit 1, six missing producer conclusions; no synthetic success results supplied.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **76 passed**, 21.94s.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`: **8 passed, 4 skipped**, 10.59s; PostgreSQL cases skip because `MAISTRO_TEST_PG_DSN` is unset.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2,852 files already formatted.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**; tests of the gate are not substitute producer conclusions.

Fresh measurements: legacy SQLite million-row index migration 11.295s, first
page 0.0009s, scoped page 0.0004s, maximum query VM instructions <2,800.
Canonical SQLite million-row load 9.080s, maximum query VM work 3,400.
The work bounds measure actual production SQL across filter/cursor scenarios,
not merely a mocked LIMIT or a wall-clock threshold.

## Acceptance and definition of done

| Requirement | This round's evidence |
| --- | --- |
| Bounded cursor pagination, stable order, maximum page | Local route and real adapter tests pass; maximum 200, timestamp/ID tie-breaking, continuation and malformed cursors covered. External driver's API target still returns an incompatible array; deployed revision UNVERIFIED. |
| Authorization/scope before database pagination | Denial-before-query, durable scope and filter tests pass on SQLite; PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Source reviewed; browser runtime UNVERIFIED. |
| Filters, export, retention without browser corpus load | Scoped/filter/capped NDJSON export and retention metadata tests pass. Native browser download runtime UNVERIFIED. Indefinite retention follows accepted ADR-037; purge belongs to #325 and is not implemented here. |
| Representative large-dataset query/index strategy | Both million-row SQLite tests executed with measured bounds above; PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max, empty pages, million-row tests | Production-path SQLite/memory tests pass, including acknowledged threaded inserts. Four PostgreSQL cases skipped. |
| Corpus-independent initial page cost | SQLite indexed reads pass after startup migration. NOT MET for memory fallback: corpus-sized sort/scan remains. |
| Bounded browser memory/DOM rows | Source caps retained rows at 500 and renders a viewport slice; browser runtime UNVERIFIED. |

## Handoff — BLOCKED

Changed file: this evidence note only. No genuinely dead code or missing
candidate ledger identity was found by the named scan; do not manufacture a
cosmetic ledger change. Existing work and all gates are preserved. No change to
Goal -> Graph -> Run -> NodeRun -> Attempt, audit authority, or authorization.

Required next input: trusted-base authorization for the four already reviewed
retained APIs, actual failed integration producer logs for the candidate, and
the live E2E target's revision identity. No merge/sync conflict exists locally.
The named gate cannot be declared fixed from this worktree. Repeating a
candidate-ledger amendment or another evidence-only repair will not remove the
trusted-base blocker. No GitHub mutation or grant edit was performed.

Final inventory validation: both
`uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
and `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
pass (3,352 and 12,591 identities respectively; no delta). `git diff --check`
passes. Only this note is changed; it is committed locally for handoff.

Progress: checked 1 assigned issue, done 0 repairs, skipped 0 issues, errors 2
named gate validations. Residual risks are recorded per criterion above.
