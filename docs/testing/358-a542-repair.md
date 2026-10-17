# Issue #358 repair — a542

## Frozen scope

- Issue #358 only; branch `auto-358`, starting HEAD `7429494f0edc32c9375e3effd8127e48e21eef93`, supplied base `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- Repair targets: reproduce integration-scope and exact-debt-ledger failures; inspect the existing audit pagination implementation and its adjacent tests. No remote mutations, grants, gate weakening, or unrelated DAG fixes.
- Allowed implementation scope: existing audit query/route/store/adapters, audit frontend, adjacent pagination tests and their inventory notes; reviewed Vulture ledger amendments only if supported by the exact scan. This report records validation and blockers.
- Starting worktree is clean; no incoming edits need salvage.

## Initial evidence

Read supplied dispatch issue body and prior result. Driver logs: ruff check/format passed; audit backend tests 77 passed; backend/core suite inventory passed. `check-3.log` failed at live `/v1/dag-runs` (HTTP 500) before audit tests. `check-6.log` used unsupported inventory suite `packages/hive-conductor/tests`. Neither is evidence of a pagination implementation failure.

Ambiguity: integration-scope is an aggregate CI gate; assume missing producer results must be distinguished from code defects rather than fabricated locally. Earlier readiness claims are not accepted without fresh evidence.

## Named gates reproduced

- Exact CI Vulture invocation: exit 1, 1,340 findings vs 1,336 trusted identities. Four `get_page` identities (PostgreSQL/SQLite/memory adapters and protocol) lack trusted-base authorization. The candidate ledger already contains exactly these four additions. No further bookkeeping amendment is warranted: the scan says explicitly that a candidate update cannot authorize them. Grant edits are prohibited. Log: job `worker-vulture.log`.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`: exit 1, all nine specialized producer results missing. This is a local evidence gap, not a reproduction of the remote producer failure. The workflow waits for same-candidate producer checks; unit/local pagination tests cannot replace those checks. Log: job `worker-integration-scope.log`.
- ADR-073 read: canonical decision audit remains admin-only. No authorization or event authority changes are justified by this lane.
- Attempted canonical ADR filename was not found; skipped that guessed filename, will resolve the actual tracked filename before reading.

Gate disposition: blocked by trusted-base authorization and missing same-candidate producer evidence. Do not manufacture references, duplicate ledger entries, or successful producer results to clear these gates. Continue with bounded acceptance validation only; do not expand into an unrelated DAG repair or a broad store redesign.

## Fresh acceptance evidence

- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: **77 passed** (19.21s). Log: `worker-audit-backend.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: **45 passed, 4 skipped** (10.50s). PostgreSQL tests skip without DSN. Log: `worker-audit-core.log`.
- Legacy million-row SQLite: index migration 8.802s, first page 0.0007s, scoped page 0.0004s; maximum query work <2,800 VM instructions. Canonical million-row SQLite: load 8.380s, maximum query work 3,400 VM instructions. Reviewed assertions exercise actual production query builders and adapters, with VM-work bounds independent of machine speed.
- `node --test tests/ci/integration-scope.test.cjs`: exit 0; these aggregator tests do not supply producer evidence. Log: `worker-integration-unit.log`.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'`: failed to connect to Docker. PostgreSQL runtime acceptance remains UNVERIFIED.
- Read actual ADR-081226-69ee and ADR-081226-7248: canonical execution and event ownership unchanged. ADR-073's admin requirement overrides any interpretation that ordinary users should browse canonical decisions.
- Frozen dispatch check-runs are for `84081fba82fc9a0aa386af6a8cc1b093b0997de2`, not the assigned candidate; no re-enumeration or remote mutations were performed.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,006 files).
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e`: PASS (3,455 / 13,939 / 23 tests). The registered e2e path fixes the driver invocation, not repository code. Log: `worker-inventory.log`.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS (both TypeScript checks and Vite). Log: `worker-frontend-build.log`. Compilation is not browser runtime evidence.

### Independent reproduction of remaining initial-page work defect

Executed a `uv run python` probe using the actual `JsonStore` and `InMemoryAuditLog`, inserting 100 then 10,000 rows through their normal write APIs and requesting `limit=1`. `sys.setprofile` counted calls to the existing `_created_at_of` and `_matches_page_filters` functions only during page reads; no production function or result was replaced. Both adapters returned one row while visiting respectively 100 and 10,000 entries. Log: `worker-memory-probe.log`.

The source corroborates the probe: `backend/services/audit_query.py:402` snapshots the whole store before sorting; `maistro/security/sentinel/audit.py:59` enumerates all entries. These are reachable through `backend/routes/audit.py:128` and the canonical bridge `backend/services/audit_bridge.py:186`. Thus a result-size ceiling does not establish a work ceiling. This round does not claim to repair either adapter: a mutation-aware indexed implementation needs its own focused regression work, not speculative edits to appease the scanner.

## Acceptance disposition

| Criterion | Evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable ordering, maximum size | PASS in 122 focused tests above: same-timestamp ties, malformed cursors, limit floor/ceiling, concurrent arrivals and empty/past-end pages. |
| Authorization/scope filters before database pagination | PASS for executed SQLite adapters and HTTP scope/admin checks. Reviewed SQL predicates precede LIMIT. PostgreSQL runtime UNVERIFIED (four skipped tests). ADR-073 admin gating is retained, not relaxed. |
| Incremental loading and virtualization | Production component issues 100-row cursor requests, caps retained entries at 500, and slices viewport rows. Build PASS; browser execution UNVERIFIED. Existing browser tests reviewed at `tests/e2e/pm-workflow.spec.ts:238-352`, not counted as run. |
| Filters, export, retention without browser corpus load | Filtered/scoped/capped NDJSON export and constant-size retention metadata tests PASS. UI export is a native download link. Purge lifecycle UNVERIFIED: existing API explicitly reports `corpus_purge: none`; #325 owns policy. |
| Representative large-dataset query/index measurements | Both million-row SQLite suites executed, measurements above. PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, maximum, empty pages, million-row tests | Exercised by the 122 passing tests; four PostgreSQL cases skipped, not passed. |
| Initial page independent of corpus size | FAIL on both reachable ephemeral adapters, independently profiled above; durable SQLite work is bounded. |
| Bounded browser memory / DOM rows | Source bounds reviewed; browser runtime/heap UNVERIFIED. A successful build is not proof of these bounds. |

## Final handoff

**BLOCKED; no production or ledger repair made.** The sole changed file is this evidence report. No test addition/removal, hence no inventory delta or inventory note required. Existing work preserved. This is not integration approval.

Required next steps, not further blind retries of this lane:

1. Supply same-candidate specialized CI producer evidence and identify the actual integration-scope producer failure. The current local missing-results failure does not identify a source fix.
2. Separately land trusted-base authorization for the four retained, already-banked `get_page` APIs, or approve a genuine architectural change eliminating them. Deleting reachable APIs or manufacturing references is not a repair.
3. Complete mutation-aware bounded reads for ephemeral stores, with write/replacement/removal and structural work-bound regressions.
4. Run PostgreSQL and browser acceptance against this candidate in an available isolated runtime. Docker socket is unavailable in this job.

Progress: checked 1 issue, done 0, skipped 0; two named gates blocked. All executed command outcomes above are fresh; prior reports are context only. No GitHub mutations, gate edits, grant edits, or unrelated DAG changes.


