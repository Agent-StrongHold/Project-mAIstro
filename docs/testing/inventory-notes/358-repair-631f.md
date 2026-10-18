---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — 631f376b

Frozen assignment: issue #358 only, worktree `/home/dev/Git/wt/auto-358`,
starting HEAD `ed0de2cc0cd7dd47763403fafa2cd334454351d6`, supplied base
`a586560170a9ce4d72ee7d750100d0178c1f69d0`; both resolve. Worktree initially
clean. Scope is the exact surfaces in the supplied job manifest, plus repository
instructions, ADR-037/073, integration-scope/Vulture gate scripts and workflow,
and this note. No other issues, authorization grants, or execution paths.

Read current driver logs check-0 through check-7 and prior result e24446fe.
Observed: check-3 live audit returns an array/200 instead of canonical denial;
check-6 names an unsupported inventory recipe. Driver local tests pass, but are
not treated as independent verification. Ambiguity: deployed target revision
and actual failed integration producer conclusions are not supplied. Assume
neither is evidence of this checkout; reproduce gates before proposing changes.
No conflict or uncommitted work requires salvage.

## Gate checkpoint

Exact requested Vulture command executed (1,200-second timeout): exit 1,
1,346 findings versus 1,342 trusted-base identities at `e067b7b0aca0`.
Four `get_page` identities lack trusted-base authorization; there are **no
candidate ledger bookkeeping deltas**. These methods serve the reachable
canonical route via `backend/services/audit_bridge.py:186`. Removing them would
break pagination; adding duplicate ledger rows would introduce incorrect debt.
The permitted candidate-ledger amendment cannot grant trusted-base approval.
No grant, scanner workaround, or artificial reference will be introduced.

Read ADR-037 and ADR-073: indefinite event retention and admin-only canonical
audit override broader issue wording. Reviewed the route, query service,
canonical SQL builder, bridge, frontend and core tests. Durable queries apply
scope/filter predicates before LIMIT. The legacy memory path copies/sorts the
corpus (`audit_query.py:402`), so corpus-independent initial cost is not proven
for every reachable configuration. Frontend source caps retained entries at
500 and windows DOM rows, but source inspection is not browser runtime proof.

Integration-scope consumes specialized producer check-run conclusions. The job
has no such conclusions or remote failure log; the cause remains UNRESOLVED.
Ran its local classifier/aggregator without fabricating success results.

## Independent validation results

Commands used 1,200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **exit 1**, trusted-base authorization failure described above. Candidate bookkeeping is already exact; no ledger amendment is warranted.
- `uv run python scripts/ci_merge_group_scope.py --json <exact frozen manifest surfaces>`: **exit 0**. Requires PostgreSQL, Hive API/UI, wheel imports, Docker build.
- `uv run python scripts/check-integration-scope.py --event-name merge_group --scope-json <classifier output>`: **exit 1**, missing `docker-build`, `hive-conductor-e2e`, `hive-conductor-e2e-ui`, `postgres (pg17)`, `postgres (pg18)`, `wheel-imports`. This local lack of producer evidence does not identify the remote failure's cause.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **76 passed**, 21.11s.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py -x -q -s`: **8 passed, 4 skipped**, 10.02s. PostgreSQL runtime and envelope remain UNVERIFIED (no test DSN).
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 2,878 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`: passed, 3,369 collected.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 12,714 collected.
- `git diff --check`: passed.

A read-only `uv run python`/httpx probe, using the failing test's
`HIVE_BASE_URL`/localhost:8101 resolution, fetched `/openapi.json` (200).
The live audit GET advertises only action/severity/actor, no cursor or limit,
and an array response. It is incompatible with this checkout's route. No
live data was changed; deployed revision is unknown. Do not make the test
accept this obsolete contract. The driver's unsupported inventory recipe
`packages/hive-conductor/tests` is not repaired by changing test expectations.

Measurements from executed million-row production-query tests:

- Legacy SQLite index migration: 9.977s; first page: 0.0007s; scoped page:
  0.0004s; maximum measured query VM instructions <2,800.
- Canonical SQLite million-row load: 8.378s; maximum query VM work: 3,400.
- Tests exercise sparse/absent filters and deep cursors, not merely an index
  name or machine-dependent timing bound.

## Acceptance and residual risks

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Bounded cursor, stable order, maximum page | Local route/adapter tests pass; maximum 200 and timestamp/identity ties covered. Live target still incompatible. |
| Authorization/scope before database pagination | SQLite scope/filter tests and canonical denial-before-query tests pass. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Source reviewed; browser runtime UNVERIFIED. |
| Filters/export/retention without whole browser corpus | Server filter/export/retention tests pass. Native NDJSON download reviewed, browser download UNVERIFIED. ADR-037 indefinite event retention preserved; purge belongs to #325. |
| Representative large-dataset query/index measurement | Both SQLite million-row tests executed, measurements above. PostgreSQL UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | Executed backend/core tests cover these, including acknowledged concurrent durable inserts. Four PostgreSQL cases skipped. |
| Corpus-independent initial page cost | Measured SQLite queries pass; NOT MET by the reachable legacy memory path that copies/sorts the corpus. |
| Bounded browser memory/DOM row count | Source has 500-entry retention cap and viewport slicing; runtime UNVERIFIED. |

## Handoff

Verdict: **BLOCKED**, not merge-ready. Only this evidence note changed; no
production/test/gate/grant/ledger contracts were weakened. No tests added or
removed. No merge conflict exists. Do not repeat evidence-only repair rounds
as if they remove these blockers.

Next requires trusted-base authorization for the retained APIs and actual
candidate producer logs. Validate a deployment of this candidate rather than
the incompatible live target. Browser/PostgreSQL acceptance and the memory
fallback cost gap remain open even after CI blockers are resolved.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; errors 2
named gate checks. Locally committed handoff only; no GitHub mutation.
