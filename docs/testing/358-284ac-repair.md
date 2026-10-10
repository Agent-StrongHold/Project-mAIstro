# Issue #358 repair — 284ac

## Frozen scope

- Issue #358 only; supplied PR #1712 is evidence, not an integration target.
- Assigned worktree `/home/dev/Git/wt/auto-358`, starting HEAD `8720bd309f0069fcae87066e8f9caaddaae4881f`, supplied base `b1f17b8d6246d347f617fb2c0b969e6798e0152b` both resolve. Starting tree clean.
- Process named vulture and integration-scope failures; inspect existing audit backend/core/frontend, adjacent tests, migration and applicable ADRs. No unrelated repairs or remote mutations.
- Candidate edit scope: audit implementation/tests if reproduced defects require it; `quality/vulture-baseline.json` only for instructed reviewed identity repair; this evidence note and an inventory note if tests change.

## Initial evidence / ambiguity

Driver check-3 fails at `packages/hive-conductor/tests/e2e/test_pm_workflow_api.py:198` (live `/v1/dag-runs` HTTP 500); target revision not established. Check-6 requests unsupported inventory suite `packages/hive-conductor/tests`. Neither is assumed to establish an audit regression. Other supplied logs pass. Previous result reported missing retention implementation, corpus-sorting legacy memory fallback, and unverified browser/PostgreSQL acceptance. These claims will be checked against source and executable evidence, not taken as approval.

Assumption: integration-scope refers to the repository gate/workflow. No develop-sync conflict exists at start, so no fetch/merge is indicated.

## Fresh results

- `uv sync --locked --extra dev`: PASS.
- Exact requested `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1328 reviewed identities / 1328 findings; trusted base 9bd1a93eefc4. No unbanked or eliminated identities; no ledger amendment justified.
- Supplied snapshot check-run 112632228148 reports integration-scope **success**, not failure, at captured head 66a8a71cbddf. Local workflow is a specialized-producer aggregator, not an application validator. This contradicts the dispatch failure label; current-head remote evidence remains UNVERIFIED. Will execute the local checker against captured producer evidence without synthesizing outcomes.
- Source independently confirms legacy memory corpus sort (`audit_query.py:402-403`) and no purge (`:79`). Retention policy belongs to #325; do not introduce a competing retention authority or claim it implemented.
- Read ADR-073 in full: bound canonical decision audit is admin-only, not a non-admin actor-filtered trail. Existing routes enforce this before querying; no authorization change is justified.
- Fresh focused backend command (`uv run pytest` audit_pagination, audit_routes, audit_convergence, noop_route_contracts `-x -q -s`): **78 passed**, 18.78s. Million-row legacy SQLite index startup 8.864s, initial page 0.0009s, scoped page 0.0006s; maximum query work <2800 VM instructions.
- Fresh core command (`uv run pytest` persistence/test_audit_pages.py and workspaces/test_store_boundary_scope_conformance.py `-x -q -s`): **50 passed, 4 skipped**, 10.36s. Canonical million-row SQLite load 7.824s, maximum query work 3400 VM instructions. PostgreSQL DSN absent; skipped cases are not proof.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: FAILED, cannot connect to Docker daemon. Cannot claim container-backed validation available merely from dispatch.
- `uv run python scripts/check-integration-scope.py --event-name pull_request` with `--result` values extracted from the frozen snapshot: PASS. Latest captured successful producer IDs for head 66a8a71cbddf: docker-build 112632565051, durable-events 112632564848, hive-conductor-e2e 112632564892, hive-conductor-e2e-ui 112632564908, object storage (MinIO) 112632564942, postgres (pg17) 112632565077, postgres (pg18) 112632564983, strike-ladder 112632565004, wheel-imports 112632564897. This is a replay of historical evidence, **not current-head integration approval**.
- `node --test tests/ci/integration-scope.test.cjs`: PASS, 12 existing tests exercising the actual workflow aggregator's fail-closed behavior and retry/latest-check rules. No gate edits.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 3137 files.
- `uv run pytest tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_revision_metadata.py tests/migrations/test_single_migration_head.py -x -q`: PASS, 7 tests.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests`: PASS, 3466 / 14918 tests; no duplicate evidence. Driver check-6's unsupported suite argument was not repaired by changing inventory policy.
- `uv run pytest packages/hive-conductor/tests/e2e/test_pm_workflow_api.py::TestDAGLifecycle::test_06_list_dag_runs -x -q`: FAIL, 1 failure, HTTP 500 at line 198. Fresh live `/health` returns 200, version 0.9.0, ready MaistroCoreBridge/MaistroServerTaskBackend, bridge configured. This is an external service at the test's default localhost:8101, not an in-process test of the assigned worktree. Exact deployed revision/traceback **UNRESOLVED**; no attempt to change canonical DAG authorization or accept the 500.
- `git diff --check`: PASS.

## Acceptance accounting

| Criterion | Fresh executed evidence and remaining gap |
| --- | --- |
| Backend bounded cursor pagination, stable order, maximum size | 78 backend and 50 core/scope tests pass. Reachable list route selects bound canonical authority or legacy fallback, caps pages at 200, and uses timestamp plus row identity to break ties. |
| Authorization/scope before database pagination | Passing route/convergence tests prove canonical admin-only refusal before I/O (ADR-073); adapter tests exercise exact org isolation and filters before LIMIT. Legacy tests prove actor aliases constrain SQL seeks before page merge. |
| Incremental loading and virtualization | Source reviewed: AuditLog.tsx requests 100-row cursor pages, retains 500 rows, mounts a fixed-height visible slice and rejects stale generations. Existing Playwright cases test actual routed component with deterministic responses. Branch-built browser execution **UNVERIFIED**; historical producer success is not substituted for fresh case-level evidence. |
| Filters/export/retention without browser corpus loading | Executed backend tests prove filtered/scoped lazy NDJSON and 10,000-entry export ceiling; UI source uses native download, not whole-response JS blobs. Browser download **UNVERIFIED**. Retention is metadata only, explicitly `corpus_purge: none`; operational purge remains owned by #325 and is not implemented here. |
| Measured query/index strategy on large data | Real million-row legacy and canonical SQLite tests pass with <2800 / 3400 VM instructions per measured query; migration tests pass. PostgreSQL million-row test **UNVERIFIED**, DSN absent and Docker endpoint unavailable. |
| Concurrent inserts, stable cursors, isolation, maximum, empty pages, million-row envelope | Existing backend/core tests execute all named behaviors on SQLite/memory; four PostgreSQL cases skip and do not count as evidence. |
| Corpus-independent initial-page cost | SQLite bounded-work and canonical memory bounded-record-read tests pass. Unconditional criterion **NOT MET** by legacy in-memory fallback: `audit_query.py:402-403` snapshots and sorts the corpus per page. Startup migration cost is also separately reported, not hidden in page timings. |
| Bounded browser memory/DOM rows | 500-entry cap and virtual slice visible in source; current-branch browser evidence **UNVERIFIED**. |

## Disposition / handoff

**BLOCKED**, not merge-ready. Neither named gate yields an actionable current defect: Vulture passes exactly, and the only captured integration-scope evidence succeeds. Altering a matching identity ledger or weakening the integration gate would not repair actual evidence. No production, tests, gates, ledgers, grants, or authority changes made. Only this evidence note changed; no test additions, so no inventory delta required.

Required next input: a fresh isolated branch-built service/browser harness and PostgreSQL DSN (or usable Docker endpoint), plus failed integration-scope producer logs if the dispatch failure label refers to a different candidate than the captured successful one. Re-run the live failure against that branch-provenance service before assigning a code repair. Do not mutate the unrelated running deployment. Separately reconcile the unconditional initial-page requirement for the legacy memory mode and retention's #325 ownership; these remain real acceptance gaps, not gate failures.

Canonical `Goal -> Graph -> Run -> NodeRun -> Attempt`, admin-only decision-audit authority, and existing authorization remain unchanged. No remote mutations or destructive git actions.

Snapshot outcome: checked 1, done 0, skipped 0, errors 1 (live-service validation failure). Next: resolve branch-provenance validation prerequisites and outstanding acceptance gaps. Local commit is the evidence checkpoint, not an implementation completion or integration approval.
