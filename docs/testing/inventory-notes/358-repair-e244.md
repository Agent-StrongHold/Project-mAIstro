---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — e24446fe

Frozen scope: issue #358 only, assigned worktree `/home/dev/Git/wt/auto-358`,
HEAD `eb1297813bf0369a8e2643065e7f8c822212bd2d`, supplied base
`00aafef9b75a1057edc2b03f2d6a71732ec9d880` (both resolved). Initially clean.
Inspection/edit surface: repository instructions, ADR-037/073, integration-scope
workflow/scripts, Vulture script/ledger and the four audit get_page APIs,
audit route/query/bridge, frontend AuditLog, adjacent audit tests, and this note.
No other issues, grants, execution authorities, or unrelated files will change.

Read prior result and current check-0 through check-7 logs. Driver check-3
received an unpaginated 200 where canonical audit requires 403; check-6 names
an unsupported inventory recipe. Backend focused tests passed in driver logs,
not yet independent acceptance evidence. Ambiguity: live target revision and
failed integration producer are unspecified. Will not infer that the target
runs this branch or invent producer conclusions. Prior Vulture blocker will
be reproduced once before deciding whether any ledger change is justified.

## Gate checkpoint

Exact requested Vulture command failed (exit 1): 1,346 findings versus 1,342
trusted-base identities at `e067b7b0aca0`. Four get_page APIs lack trusted-base
authorization. Candidate already contains all four; production calls them via
`backend/services/audit_bridge.py:186`. No unbanked candidate identity or dead
method was demonstrated. Duplicating candidate rows cannot fix this; no ledger
or grant change is justified. Required action is outside this repair lane:
reviewed authorization must land in the trusted base first.

Integration-scope is an aggregator of producer conclusions, not a package test.
The supplied logs contain no failed producer conclusion. This ambiguity remains
UNRESOLVED; local tests cannot be substituted for GitHub check-run evidence.
The attempted adjacent `tests/e2e/conftest.py` path was not found; skipped.

Read ADR-037/073: indefinite event retention and admin-only canonical audit
remain authoritative. Source review confirms durable SQL scopes before LIMIT;
memory fallback (`audit_query.py:402`) still copies/sorts the corpus and does
not meet corpus-independent first-page cost. Frontend retains at most 500
entries and renders a viewport slice; runtime browser behavior is UNVERIFIED.

## Fresh validation

Commands used 1,200-second timeouts:

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **76 passed**, 22.27s.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`: **8 passed, 4 skipped**, 11.25s. No PostgreSQL DSN configured.
- Exact Vulture command specified in the assignment: **exit 1**, trusted-base authorization failure, not missing candidate ledger rows (lines 1004, 1013, 1075, 1174).
- `uv run python scripts/ci_merge_group_scope.py --json <frozen manifest paths>`: **exit 0**; requires PostgreSQL, Hive API/UI, wheel imports, Docker build.
- `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classifier output>`: **exit 1**, six missing producer conclusions. No fabricated `--result` supplied. This is not proof of the unspecified remote failure's cause.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**; aggregator behavior is not evidence that producers passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (2,878 files).
- `git diff --check`: passed.

Measured legacy SQLite million-row index migration 10.663s; first page
0.0011s; scoped page 0.0004s; maximum measured query VM instructions <2,800.
Canonical SQLite million-row load 9.293s; maximum query VM work 3,400.

Read-only live probe using `uv run python` + httpx, with the same HIVE_BASE_URL
resolution as the failing API test: `/openapi.json` returned 200. Its audit GET
advertises only action/severity/actor parameters and an array response; no
limit or cursor. This independently confirms an incompatible live target
contract, not the paginated route checked into this branch. Exact deployed
revision remains UNVERIFIED. No live data or server process was changed.

Both `uv run python scripts/check-suite-inventory.py --suite <suite>` checks
passed: Hive backend 3,369 tests; core 12,714. No tests were added or removed.

## Acceptance and handoff

| Criterion | Evidence / remaining gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | Executed route/adapter tests pass: 200 maximum, timestamp/ID ordering, continuation, malformed cursors. Live API contract is incompatible. |
| Authorization/scope before database pagination | Executed SQLite scope/filter and canonical denial-before-query tests pass. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | AuditLog source uses cursor pages and viewport slicing; browser runtime UNVERIFIED. |
| Filters/export/retention without browser corpus loading | Executed server filter/export/retention tests pass. Source uses native NDJSON download. Browser download UNVERIFIED. Indefinite event retention follows ADR-037; purge policy remains #325. |
| Representative large-dataset query/index measurements | Both SQLite million-row production-query tests executed; measurements above. PostgreSQL envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty pages, million-row coverage | Executed backend/core tests pass, including acknowledged concurrent durable inserts. Four PostgreSQL cases skipped. |
| Corpus-independent first-page cost | SQLite indexed queries measured; NOT MET for memory fallback, which copies/sorts corpus. |
| Bounded browser memory/DOM | Source has 500-entry cap and windowed rows; browser runtime UNVERIFIED. |

BLOCKED: no safe gate repair was demonstrated. The only changed file this round
is this note. Candidate ledger edits cannot supply trusted-base authorization,
and aggregator repairs without producer logs would be guessed changes. No grant,
gate, production, or test contract was weakened. No merge conflict exists.

Next: obtain trusted-base authorization for the already reviewed APIs, actual
failed integration producer logs for the candidate, and deploy this candidate
to an isolated API/browser validation target. Do not repeat evidence-only repair
rounds as if they remove these blockers. Memory-backend cost remains a product
acceptance gap even after CI/environment blockers are resolved.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 2 named gate
validations. This evidence is committed locally; no GitHub mutation performed.
