# Issue #358 repair — job 1e2a

## Frozen scope

Only issue #358; assigned worktree `/home/dev/Git/wt/auto-358`, branch
`auto-358`, starting HEAD `f447e44cc5ee440e5302b769732236768ed5557a`,
base `7334621bf797178dd992622d55aaead33bf9d094`. Starting tree clean.
Snapshot: supplied dispatch-context.json and check-0 through check-7 logs;
no GitHub refresh or mutations. Focus: named integration-scope and exact
vulture gates, existing audit pagination production paths and adjacent tests.
Potential edit scope: audit query/adapters and their tests, inventory note,
reviewed vulture identities if the scanner actually identifies unbanked debt,
and this report. No scheduler, event authority, or authorization changes.

## Initial evidence / assumptions

Driver check-3 fails on live GET /v1/dag-runs returning 500 in
`packages/hive-conductor/tests/e2e/test_pm_workflow_api.py:198`.
Driver check-6 requests an unsupported inventory suite; it is not a count
mismatch. Driver audit-specific tests passed (77); these will be rerun.
Prior result alleges four banked identities lack trusted-base authorization,
nine integration producer results are absent, and memory adapters scan the
whole corpus. These are claims to revalidate, not permission to weaken gates.
Assumption: this is a writer repair assignment; no develop conflict is present,
so no network sync is necessary. Mandatory local commit will preserve results.

## Named gates (fresh)

Exact Vulture command exited 1: four `get_page` identities need trusted-base
authorization; no unclassified identities. It resolved trusted base 56332162cf63,
not the supplied develop snapshot (provenance policy, not changed here).
Integration-scope with `--event-name pull_request` exited 1: all nine producer
results missing. This local evidence gap is not proof of the remote root cause.
Docker socket is unavailable, so PostgreSQL runtime cannot be claimed.
Logs: job `worker-vulture.log`, `worker-integration-scope.log`.

The four retained identities already occur in `quality/vulture-baseline.json`
at lines 997, 1006, 1068, 1170. The real HTTP bridge calls `audit_log.get_page`
at `backend/services/audit_bridge.py:186`. Deleting these APIs or adding
scanner-only calls would not repair actual dead code. No ledger amendment is
needed or defensible for this scan; a candidate amendment cannot grant approval.
Frozen dispatch check evidence names SHA 84081fba82fc, not the assigned HEAD;
it cannot establish same-candidate integration producer success.

Read ADR-073, ADR-081226-69ee and ADR-081226-7248. Canonical decision audit
remains admin-only; scope criteria do not override that requirement. This round
changes neither the execution spine nor event ownership.

## Focused validation checkpoint

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: 77 passed (18.83s).
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: 45 passed, 4 PostgreSQL cases skipped (10.14s).
- Legacy million-row SQLite: index migration 8.938s, initial page 0.0008s,
  scoped page 0.0007s, maximum VM work <2,800 instructions.
- Canonical million-row SQLite: load 8.102s, maximum VM work 3,400 instructions.
  Both measurements execute real adapters, not mocked query results.
- Logs: job `worker-backend.log`, `worker-core.log`.

## Remaining acceptance evidence

Fresh `uv run python` profiling probe seeded real `JsonStore` and
`InMemoryAuditLog` objects through their write APIs, then requested limit=1.
`sys.setprofile` counted existing per-entry functions only during reads (no
production result replacement): both adapters visited 100 / 10,000 entries for
100 / 10,000-row corpora, respectively. Each returned exactly one row.
`worker-memory-probe.log` records the result. Production source agrees:
`backend/services/audit_query.py:402` snapshots the entire store;
`maistro/security/sentinel/audit.py:59` enumerates every entry. These paths
remain reachable from `backend/routes/audit.py:128` (legacy fallback) and
`backend/services/audit_bridge.py:186` (bound core). **Initial-page work is
not independent of corpus size on either ephemeral adapter.** A repair needs
mutation-aware indexes, including the bridge's direct `_entries.append` writer;
a query-only cache would introduce stale/security-sensitive reads.

Reviewed `frontend/src/pages/AuditLog.tsx`: 100-row cursor requests, a 500-entry
sliding window, viewport slicing with overscan, filter-generation protection,
and native streamed export link. Existing browser tests in
`tests/e2e/pm-workflow.spec.ts:238-352` cover these behaviors but were not run.
A build is not browser runtime evidence. Retention is constant-size metadata,
not an implemented purge lifecycle (`audit_query.py` reports `corpus_purge: none`).

| Acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | PASS in focused tests: ties, maximum/floor, malformed cursors, empty/past-end pages. |
| Authorization/scope before database pagination | PASS in SQLite adapter/HTTP tests, including admin-only canonical decisions. PostgreSQL runtime UNVERIFIED (skipped). |
| Incremental loading and virtualization | Production source reviewed and frontend build PASS; browser runtime UNVERIFIED. |
| Filters, export, retention without whole-corpus browser load | Filter/scoped/capped streaming export and constant-size retention metadata tests PASS; actual retention purge UNVERIFIED, owned by #325. |
| Representative large-dataset query/index measurements | Both million-row SQLite suites PASS with VM-work bounds above; PostgreSQL envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, maximum limit, empty pages, million-row tests | 122 focused tests PASS, four PostgreSQL cases skipped, not passed. |
| Initial page cost independent of audit-log size | FAIL: real limit=1 memory probes perform corpus-sized work. Durable SQLite query work is bounded. |
| Browser memory/DOM row count bounded | Source caps reviewed; browser/heap runtime UNVERIFIED. |

## Other fresh validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,006 files).
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e`: PASS (3,455 / 13,939 / 23). Use the registered `tests/e2e` recipe, not the driver's unsupported `tests` path. Log: `worker-inventory.log`.
- `node --test tests/ci/integration-scope.test.cjs`: 12 PASS. These aggregator unit tests do not substitute for producer results. Log: `worker-integration-unit.log`.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS (exit 0). Log: `worker-build.log`.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'`: FAIL, cannot connect to daemon. No PostgreSQL runtime provisioned.

## Handoff

**BLOCKED; evidence-only commit, not integration approval.** Changed file:
`docs/testing/358-1e2a-repair.md`. No production, test, ledger, grant, or gate
changes; no inventory delta. Existing implementation preserved. No remote
mutations. No unresolved merge conflict exists.

Required inputs/work:

1. Same-candidate producer evidence identifying the actual integration-scope
   failure; local missing-result output cannot diagnose a remote source defect.
2. Separately approved trusted-base authorization for four retained APIs, or a
   justified architectural change that actually eliminates them. Their candidate
   ledger entries already exist; adding duplicates cannot fix provenance.
3. Mutation-aware bounded ephemeral reads with structural work-bound regressions.
4. Available PostgreSQL/browser runtimes for remaining acceptance validation.

Progress: checked 1 issue, done 0, skipped 0, errors/blockers 2 named gates;
next: resolve provenance/producer inputs and the remaining acceptance defects.
