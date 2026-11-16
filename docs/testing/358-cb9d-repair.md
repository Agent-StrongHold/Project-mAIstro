# Issue 358 repair — cb9d

## Frozen scope

- Issue #358 only; assigned worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `af496ceb3f2bce6cf1648112fb45d0054df2ae6f`; supplied develop base `34795962548a33f6b6f7e1234dcea201a9df96ef`.
- Evidence: supplied dispatch-context.json and check-0 through check-7 logs; prior result 35687 if present.
- Candidate repair files: `packages/hive-conductor/tests/e2e/test_pm_workflow_api.py`, directly implicated audit production/test files if reproduction requires it, this report and an inventory note; `quality/vulture-baseline.json` only if the explicitly requested gate demonstrates retained debt. Integration-scope policy is inspection/validation only, not permission to weaken it.
- Acceptance inspection: existing audit routes/query/store, AuditLog UI, pagination/convergence/store/migration/browser tests and relevant ADRs.

## Initial evidence and assumptions

Clean worktree at assigned HEAD. Driver check-3 fails because a canonical-engine E2E test expects global audit 403 but receives 200. Investigate authorization/principal setup rather than changing expected status without evidence. Driver check-6 uses an unregistered inventory suite (`packages/hive-conductor/tests`); find its registered E2E recipe instead. Other driver logs report passing checks but are not independent proof here.

Supplied base-to-head diff contains extensive unrelated history. Preserve it; do not rewrite or discard prior work. No merge conflict exists at entry, so do not fetch/merge a moving develop merely to change the frozen scope.

## Inspection checkpoint

- Requested exact vulture scan passes: 1,328 findings / reviewed identities, zero unclassified. No ledger amendment is justified.
- Production `routes/audit.py` returns AuditPage and denies canonical non-admin requests before query I/O. Driver instead receives an old array response. The assertion must not be relaxed to accept that contract.
- ADR-073 requires admin-only canonical decision audit; personal scope is only the unbound legacy fallback. Preserve this distinction and the existing execution model.
- `services/audit_query.py` explicitly sorts every legacy in-memory entry per request. The prior unqualified initial-cost gap remains visible in current source; durable performance alone cannot close it.
- Integration-scope is an exact-candidate aggregate; no failed producer is identified in the assignment. Inspect captured evidence once and run its local contract, but do not manufacture successful producer conclusions.

## Executed validation checkpoint

- Focused backend audit/convergence/pagination/noop suite: **78 passed** in 17.30s. Million-row index migration 7.974s; initial page 0.0006s, scoped page 0.0004s; maximum query work <2,800 SQLite VM instructions.
- Independent GET `http://localhost:8101/openapi.json` returns an audit operation with only action/severity/actor parameters and an array response: it does not advertise this checkout's limit/cursor/AuditPage contract. Deployed revision is unknown. Preserve the test assertion; fix the external driver target, not authorization.
- Frozen dispatch check runs are for `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not assigned HEAD. All nine integration producers and integration-scope succeeded there. Several unrelated checks failed there. This is not evidence for the unidentified failing merge-group candidate; cause remains UNRESOLVED after the two allowed inspections.
- `DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}'`: exit 1, cannot connect to daemon. Isolated Compose/API/browser and PostgreSQL validation are blocked in this environment.
- ADR-037 defaults events to indefinite retention. Do not invent purge policy under #358; retention metadata plus bounded exports are consistent with that default, while #325 owns purge policy. ADR-068/073 retain authorization authority; ADR-081426-1f7c retains Attempt mechanics separation. No authority changes are needed for this repair.

## Final validation

Commands run with 600–1,200s validation timeouts (inspection commands 120s):

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_migration_chain.py -x -q -s
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests
uv run pytest tests/test_check_integration_scope.py -x -q
node --test tests/ci/integration-scope.test.cjs
npm --prefix packages/hive-conductor/frontend run build
uv run python scripts/check-api-route-contracts.py
```

All commands above passed; core/migration batch has **52 passed, 22 skipped**
(PostgreSQL/service-dependent execution not proven). Canonical SQLite million-row
load 7.498s; maximum query work 3,400 VM instructions. Ruff reports 3,168 formatted
files. Inventory is unchanged: backend 3,589, registered E2E 23, core 15,423.
Gate unit tests: 18 Python + 12 Node passed. Frontend TypeScript/Vite build passed.
Route-contract gate: 284 handlers, 15 audited routes, zero canned responses.

Executed `check-integration-scope.py --event-name pull_request` with the nine
`--result NAME=success` arguments derived solely from the captured check-run
records (latest ID per name, asserted SHA `bc293cd790b6852da71b3e251dcecdda84bbde9b`).
This **historical replay passed**. It is explicitly NOT an assigned-head producer
run or proof the unidentified merge-queue failure was fixed. No missing result
was filled in and no gate was changed.

A fresh deterministic Python probe called production `page_entries(limit=1)` on
a dict subclass counting entries yielded by `items()`. With 100 entries it visits
100; with 10,000 it visits 10,000. Thus the legacy memory fallback's initial cost
still grows with corpus size. Core `InMemoryAuditLog` is separately indexed at
writes; its existing tests pass. Do not conflate these adapters.

The local convergence suite executes the exact PM E2E assertion against both
production authority bindings and real authentication; both pass. The external
old-array response is not grounds to weaken that assertion. No repeat writes to
the shared external deployment were needed: its read-only OpenAPI established
the mismatch independently.

## Acceptance matrix

| Criterion | Executed evidence / limitation |
| --- | --- |
| Bounded cursor, stable order, maximum page size | 78 backend + 52 core/migration tests pass; default/max, ties, continuation and invalid cursors covered. External driver target serves a different contract. |
| Authorization/scope before database pagination | Real SQLite scoped/filter queries and canonical deny-before-query tests pass. PostgreSQL runtime UNVERIFIED. |
| Incremental frontend loading and virtualization | Production source inspected; TypeScript/Vite build passes. Browser runtime UNVERIFIED because isolated Docker is unavailable. |
| Filters, export, retention avoid full browser corpus | Filter and capped NDJSON stream tests pass; retention reports constants, no corpus. ADR-037 indefinite default preserved; purge is not implemented (#325). Browser download runtime UNVERIFIED. |
| Measured large-data query/index strategy | Both actual million-row SQLite suites pass with deterministic VM-work bounds above. PostgreSQL performance UNVERIFIED. |
| Concurrent inserts, cursor stability, scope isolation, max limit, empty pages, million-row envelope | Executed backend/core suites cover these, including acknowledged threaded writes. PostgreSQL cases skipped. |
| Initial page cost independent of corpus | NOT MET across reachable modes: legacy memory probe visits every row for a one-row page. Indexed durable queries pass after startup indexing. |
| Browser memory/DOM bounded | Source caps retained rows at 500 and renders a viewport slice. Browser/heap runtime UNVERIFIED. |

## Handoff — BLOCKED

Changed file: **this report only**. No new/removed tests, no inventory delta, no
source or ledger/gate edits. Existing tests provide meaningful evidence; do not
invent a code repair when the named gate is green and the supplied API endpoint
is not this implementation. Local commit records the blocked handoff, not issue
completion or integration approval.

Required next inputs/actions: configure the driver to use a fresh isolated build
of this candidate and the registered `packages/hive-conductor/tests/e2e` inventory
suite; restore Docker availability; supply the actual failing merge-group SHA and
producer log. Separately, #358's legacy memory query still needs a mutation-safe
indexed storage repair; a request-local cache cannot safely fix mutable JsonStore
replacement/deletion. No competing audit authority was introduced here.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 environment
block (Docker unavailable). Remote integration failure and acceptance gaps remain
open. Do not repeat this round against the same mismatched external deployment.



