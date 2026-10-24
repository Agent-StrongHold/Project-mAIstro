# Issue #358: bounded repair attempt 969f

## Snapshot and disposition

Assigned worktree: `/home/dev/Git/wt/auto-358`, branch `auto-358`.
Starting HEAD verified: `ad582e53d61a0cfce334b854ccf80fb571f0ea43`.
Assigned base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
The worktree was clean: no incoming changes needed salvage, and no merge was
pending. Only issue #358 and its supplied evidence were processed. No fetch,
GitHub mutation, gate weakening, authorization change, or competing execution
or audit authority was introduced.

**BLOCKED: no evidence-backed implementation or ledger repair was available for
the named gates.** This commit records fresh validation, not a production fix
or integration approval. Repeating the same lane without the prerequisites
below will not clear it. Existing implementation and prior repairs are preserved.

## Named gates: freshly executed

Logs are in
`/home/dev/maistro/jobs/969f17cea29842a1a20208278c5059ca/worker-*.log`.
Long-running validations were allowed 1,200 seconds.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  **FAIL**: 1,336 trusted identities versus 1,340 findings. The four additions
  are `get_page` on `PgAuditLog`, `SqliteAuditLog`, the `AuditLog` protocol, and
  `InMemoryAuditLog`. The candidate ledger already records each exactly once;
  the entire ledger diff against the assigned base consists of these four
  additions. They are retained production APIs, called by
  `backend/services/audit_bridge.py:186`, outside the scanner's source roots.
  The gate explicitly requires separately landed trusted-base authorization.
  The lane permits ledger bookkeeping, not grant edits. Adding duplicate rows,
  deleting required APIs, or adding artificial references would not be a repair.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`
  **FAIL CLOSED**: no results supplied for docker-build, durable-events,
  hive-conductor-e2e, hive-conductor-e2e-ui, object storage (MinIO), postgres
  (pg17), postgres (pg18), strike-ladder, or wheel-imports. This local command
  cannot establish the remote failure's cause without same-candidate producer
  evidence. The frozen dispatch contains all nine successful producers and a
  successful integration-scope result for **older SHA `84081fba82fc`**, not
  the assigned candidate. These historical checks cannot authorize this head.
  No new GitHub enumeration or synthetic success inputs were used.
- `node --test tests/ci/integration-scope.test.cjs`: **PASS**, 12 tests.
  Aggregator unit tests do not replace producer evidence.

## Focused acceptance validation

| Acceptance criterion | Fresh evidence and limits |
| --- | --- |
| Backend bounds cursor pages, stable ordering, maximum size | **77 backend tests pass** across `test_audit_convergence.py`, `test_audit_pagination.py`, `test_audit_routes.py`, and `test_noop_route_contracts.py`, using `uv run pytest ... -x -q -s`. Includes maximum/floor limits, same-timestamp ties, malformed cursors, empty and past-end pages. |
| Authorization/scope before database pagination | Those backend tests and **45 core tests pass** in `tests/persistence/test_audit_pages.py` plus `tests/workspaces/test_store_boundary_scope_conformance.py`. SQLite predicates precede LIMIT; canonical decision routes retain ADR-073's admin gate before I/O. Four PostgreSQL cases skip; PostgreSQL execution is **UNVERIFIED**. |
| Incremental loading and virtualization | Production `frontend/src/pages/AuditLog.tsx` fetches 100-row cursor pages, retains at most 500 entries, and slices rendered rows by viewport. `npm --prefix packages/hive-conductor/frontend run build` **PASS**. Existing browser tests cover late responses, sentinel continuation and bounded rows, but **browser runtime is UNVERIFIED this round**. |
| Filters/export/retention do not load corpus into browser | Scoped/filtered export and retention-metadata tests **PASS**; the production UI downloads NDJSON directly rather than accumulating it in JavaScript. A purge lifecycle is **UNVERIFIED**; the legacy endpoint explicitly reports `corpus_purge: none`. Retention-policy implementation remains outside this issue's assigned repair. |
| Representative large-dataset query/index measurements | Both **million-row SQLite tests pass**. Legacy index migration: 8.228s; initial page: 0.0006s; scoped page: 0.0005s; maximum query work <2,800 VM instructions. Canonical SQLite load: 7.793s; maximum query work: 3,400 VM instructions. PostgreSQL million-row envelope **UNVERIFIED**. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty and million-row tests | Executed in the 122 passing focused tests above; PostgreSQL cases explicitly skipped rather than claimed passing. |
| Initial-page cost independent of audit-log size | **NOT MET** on both reachable ephemeral adapters, independently measured below. Durable SQLite measurements do establish bounded query work. |
| Browser memory and DOM row count bounded | Source imposes the 500-entry retained window and viewport slicing. Runtime browser/heap verification **UNVERIFIED**, not implied by successful TypeScript compilation. |

ADR reconciliation: ADR-073's admin-scoped canonical decision audit overrides
any interpretation that ordinary users should read their canonical decisions.
Legacy own-actor filtering does not relax that gate. ADR-081226-69ee's canonical
Graph/Run/NodeRun/Attempt ownership remains unchanged; this issue has no mandate
to repair the live DAG execution service or introduce another store authority.

### Newly reproduced unbounded-work evidence

An executed instrumentation probe calls the actual query methods with `limit=1`,
without replacing the implementation or fixing the result under test:

| Adapter | Corpus rows | Returned rows | Visited entries |
| --- | ---: | ---: | ---: |
| `services.audit_query.page_entries` over `JsonStore` | 100 | 1 | 100 |
| Same legacy adapter | 10,000 | 1 | 10,000 |
| `InMemoryAuditLog.get_page` | 100 | 1 | 100 |
| Same canonical ephemeral adapter | 10,000 | 1 | 10,000 |

Legacy `_sorted_ascending` snapshots and sorts the whole mapping at
`backend/services/audit_query.py:402`. Canonical memory pagination enumerates
all `_entries` at `maistro/security/sentinel/audit.py:59`. The latter is an
additional confirmed failure beyond the previous report's legacy-only probe.
Both return bounded pages but do not perform bounded work. The production route
selects the canonical adapter when bound, otherwise the legacy query seam.
A mutation-aware index needs to cover append, replacement and removal (including
bridge writes); a length cache would silently miss same-length replacement.
This is unresolved implementation work, not something a ledger edit can fix.

## Other checks and environment limits

- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3,006 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e`:
  **PASS** (3,455 / 13,939 / 23 tests; no duplicate evidence).
  Driver `check-6.log` requested the unregistered parent
  `packages/hive-conductor/tests`; the existing registered `.../tests/e2e`
  recipe is the correct invocation. No gate or inventory baseline changed.
- Driver `check-3.log` fails `test_pm_workflow_api.py:198`: the external
  `/v1/dag-runs` endpoint returned 500 instead of 200. This is real failing
  evidence, but does not identify an audit-pagination defect or prove that the
  external server runs this worktree. No assertion was weakened and no DAG
  implementation was changed on speculation.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format ...`: **FAIL**,
  cannot connect to Docker. No PostgreSQL runtime claims are made.

## Handoff prerequisites

1. Supply same-candidate specialized producer logs/results for integration-scope;
   identify an actual failed producer before assigning a source repair.
2. Obtain trusted-base authorization through the separate governance workflow
   for the four already-reviewed retained `get_page` identities. This worker
   did not and must not manufacture that authorization.
3. Repair both ephemeral pagination paths with mutation-aware bounded query
   indexes, preserving existing audit ownership and scope decisions. Run a
   structural work-bound regression against the old implementation as well as
   concurrency/replacement/removal tests.
4. Execute PostgreSQL migration/performance and browser acceptance tests against
   the candidate in an available, isolated runtime. Do not count historical
   successful checks or external-service responses as candidate validation.

Only this report is changed in this attempt. No tests were added or removed,
so there is no inventory delta. Progress: checked 1 issue, done 0, skipped 0;
two named gate blockers remain. Next: the prerequisites above, not another
unqualified retry of the same repair assignment.
