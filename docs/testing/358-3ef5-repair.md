# Issue 358 repair — job 3ef5bdd

## Frozen scope and initial evidence

- One item: issue #358, branch `auto-358`, start `95808ad3cd859b50923f5a37088740a1cf4b84c8`, supplied base `2779c99a72b464f9399306dfc40e6ce82a76b59e`. Initial worktree clean; no merge in progress. No fetch or remote mutation.
- Review scope: supplied dispatch/check logs and prior result; issue's existing audit routes/query/bridge/stores, core audit adapters/protocol, audit frontend and adjacent tests; relevant ADRs and named gate scripts/workflows.
- Potential repair scope frozen to existing core audit adapters, their protocol and adjacent audit tests, reviewed Vulture identities if justified, and this report/inventory note. Do not redesign legacy memory storage or unrelated integration producers in this bounded gate-repair round.
- Read repository instructions, docs map and Accepted ADR-073. Canonical audit must remain admin-scoped; keep the existing authority, not a replacement store or authorization path.
- Fresh exact Vulture command reports four already-banked `get_page` APIs, absent from trusted base `c560d4ccad82`; candidate banking does not authorize them. No duplicate rebanking or grant edit.
- Fresh `check-integration-scope.py --event-name pull_request` fails closed on nine missing producer results. This is not evidence of a checker defect. Docker at the prescribed socket is unavailable.
- Driver checks: ruff/format and 77 backend tests pass; external E2E gets an old list-shaped 200 instead of canonical admin-only 403. Inventory request for `packages/hive-conductor/tests` is invalid; use registered `packages/hive-conductor/tests/e2e` recipe.
- Ambiguity: supplied base differs from Vulture's resolved trusted base; retain the gate's provenance logic, do not override it. External HTTP server provenance is unknown; retain strict assertions and validate local production composition separately.

## Progress

Initial named gate failures reproduced. Existing `get_entries` consumers have different contracts (agent filtering, limits larger than the page maximum, and insertion ordering for memory). Replacing them merely to make Vulture see `get_page` would change behavior outside this repair; no scanner-only caller or suppression is justified. The four retained APIs are called by the production Hive bridge outside the gate's `packages/*/src` scan. Their existing candidate ledger entries are correct and require trusted-base authorization.

Fresh focused validation: 77 backend tests passed; 45 core tests passed, 4 PostgreSQL cases skipped. This includes a real bound SQLite Container denying canonical audit reads to non-admins, legacy scope-before-limit tests, concurrent inserts, cursor ties, clamps/empty pages and both million-row envelopes. Measured legacy index construction 9.174s, initial page 0.0006s, scoped page 0.0003s, VM work <2,800; canonical load 8.365s and max VM work 3,400.

A guessed ADR-068 filename was not found; skipped that path, resolved and read `ADR-068-unified-authorization-and-elevation.md`. Also read Accepted `ADR-081226-69ee-graph-node-execution-model.md`. No new execution or authorization authority is appropriate. Frontend source inspection shows incremental cursor reads, 500 retained entries and viewport slicing, plus direct NDJSON download; runtime still requires executed browser evidence.

Fresh external E2E run reproduces `test_pm_workflow_api.py:271`: expected 403, got list-shaped 200 (7 passed, 13 skipped before failure). The current route returns an AuditPage or rejects the non-admin before I/O. This mismatch does not establish the external deployment's code provenance, and must not be papered over with a permissive assertion.

Fresh counted-mapping probe of production `page_entries(limit=1)` visits 100/100 and 10,000/10,000 rows. `_sorted_ascending` at `backend/services/audit_query.py:386` remains corpus-sized on the reachable unbound memory path. The docstring correctly admits this limitation; a passing durable envelope does not satisfy the unconditional definition of done. Core `InMemoryAuditLog.get_page` also explicitly scans its corpus. Neither limitation is safely repaired by editing a ledger.

## Commands and outcomes

Executed from the assigned worktree with long timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — FAIL: four live `get_page` identities lack trusted-base authorization. Candidate already banks exactly those four; no ledger edit justified. Output captured in the job's tool transcript.
- `uv run python scripts/check-integration-scope.py --event-name pull_request` — FAIL: missing docker-build, durable-events, hive-conductor-e2e, hive-conductor-e2e-ui, object storage (MinIO), postgres (pg17), postgres (pg18), strike-ladder, wheel-imports results. No fabricated `--result ...=success` arguments. Local invocation cannot certify hosted producer runs.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` — FAIL: daemon unavailable. No database or application service was started or changed.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` — 77 passed (`repair-backend.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` — 45 passed, 4 skipped (`repair-core.log`).
- `uv run pytest packages/hive-conductor/tests/e2e/test_pm_agent.py packages/hive-conductor/tests/e2e/test_pm_workflow_api.py -q -x` — 1 failed, 7 passed, 13 skipped (`repair-e2e.log`).
- `uv run ruff check .` — PASS; `uv run ruff format --check .` — PASS, 2,987 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e` — PASS: 3,396 / 13,780 / 23 cases. No tests added or counts changed; no inventory delta needed.
- `node --test tests/ci/integration-scope.test.cjs` — 12 passed; checker correctness is not producer evidence.
- `npm --prefix packages/hive-conductor/frontend run build` — PASS (`repair-build.log`), not a browser-runtime pass.
- Inline `uv run python` counted-mapping probe — confirms full corpus traversal for a one-row page, as above; ledger inspection confirms four retained identities.
- `git diff --check` — PASS.

Named log files are under `/home/dev/maistro/jobs/3ef5bdd264a548fdae22c11c72da8e4c/`.

## Acceptance matrix

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Bounded cursor pagination, stable order, maximum page size | Backend and core tests pass for SQLite and memory, including ties, clamp and continuation. PostgreSQL runtime UNVERIFIED (4 cases skipped). |
| Scope before database pagination | Real SQLite scope/isolation tests pass; real bound Container rejects non-admin canonical audit access. External E2E remains failing; deployed provenance UNVERIFIED. ADR-073 admin-only core decision policy takes precedence over personal legacy scope. |
| Frontend incremental loading and virtualization | Source inspection plus production build PASS. Browser-runtime behavior UNVERIFIED; existing Playwright configuration targets an external server. |
| Filters, export, retention without browser-wide corpus load | Filter and capped/scoped streaming export tests pass; source uses a direct download. Retention metadata tests pass, but endpoint reports `corpus_purge=none`; lifecycle retention UNVERIFIED/deferred to #325. |
| Representative large-dataset query/index measurements | Two million-row SQLite envelopes executed, measured above. PostgreSQL million-row envelope UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max, empty, million-row tests | 122 focused tests passed, including actual durable queries and insert interleaving. Four PostgreSQL cases skipped. |
| Initial page independent of total size | NOT MET on reachable memory fallback: one-row page visits the entire corpus; durable SQLite seeks are bounded after startup indexing. |
| Browser memory/DOM bounded | Source caps retained rows at 500 and renders viewport slices; browser execution UNVERIFIED. |

## Handoff

**BLOCKED — evidence-only handoff, not a completed implementation repair or integration approval.** Only this report changed. No production code, tests, gates, ledger/grants, remote refs or GitHub state changed. Existing work is preserved. No speculative refactor is a substitute for missing authorization or producer evidence.

Next: obtain trusted-base authorization for the four reviewed live APIs through the owning process; provision a candidate-specific integration stack and prove its source revision; repair/index the reachable memory read path in a bounded implementation round; execute PostgreSQL and browser acceptance. The supplied integration-scope failure and previous blocker are not resolved.

Progress: checked 1 issue; done 0 issues; skipped 0 issues; errors 3 (Vulture, integration-scope, external E2E).
