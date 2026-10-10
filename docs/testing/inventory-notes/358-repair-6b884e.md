---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# Issue 358 repair — job 6b884e

Frozen scope: issue #358 only, assigned worktree `/home/dev/Git/wt/auto-358`,
branch `auto-358`, starting HEAD `28505662d7b6abb055beced91622421f56ad2877`,
supplied base `b35c76e035b3ee60789f9eac3e82526e23aba2e1`.
Initial working tree clean. Scope files: existing audit route/query/bridge,
core audit page adapters, AuditLog frontend and adjacent tests; integration-scope
workflow/checker and vulture checker/ledger for named CI failures; this note.
No remote mutation, grant edits, or unrelated repairs.

Initial evidence: driver check-3 fails because the service returns the old audit
array contract instead of expected canonical authorization. Prior job result is
BLOCKED; prior claims will be revalidated. Ambiguity: running integration service
may not match this checkout; inspect independent OpenAPI before changing tests.
Do not infer missing integration producer conclusions or manufacture approvals.

## First validation checkpoint

- Exact requested vulture command: **exit 1**, 1349 findings, zero unclassified;
  four retained `get_page` APIs lack trusted-base authorization. Output saved at
  `/tmp/358-6b884e-vulture.log`. This is authorization debt, not an unbanked
  candidate identity; do not add duplicate rows or edit grants.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  **exit 1**, all nine producer conclusions missing. This local invocation
  cannot establish the remote failure cause without exact-candidate evidence.
- `node --test tests/ci/integration-scope.test.cjs`: **12 passed**.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`:
  **76 passed**, 19.95s; million-row index startup 9.772s, first page 0.0007s,
  scoped page 0.0004s, max query VM instructions <2800.
  Log: `/tmp/358-6b884e-backend.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py
  -x -q -s`: **8 passed, 4 skipped**, 9.46s; canonical SQLite million-row load
  7.983s, max query VM work 3400. PostgreSQL remains unverified.
  Log: `/tmp/358-6b884e-core.log`.

Accepted ADR-073 keeps the canonical decision audit admin-only; no reconciliation
requires weakening this contract. Reviewed production pagination/authorization,
SQL indexes, export/retention, and frontend windowing. Memory fallback still
sorts the whole corpus per request; retention declares no purge (#325).

## Gate and environment findings

All driver logs inspected: check-0/1/2/4/5/7 pass; check-3 fails the audit
integration assertion; check-6 fails because `packages/hive-conductor/tests`
has no inventory collection recipe. No remote specialized producer conclusions
were supplied. The integration-scope workflow requires success on the exact
candidate SHA; local unit results are not substitutes for those conclusions.
Remote failure cause remains UNRESOLVED, not attributed to a guessed producer.

Independent `uv run python` HTTPX GET of
`http://localhost:8101/openapi.json` returned 200. `/v1/audit` advertises only
`action`, `severity`, `actor`, and an array response. Checkout
`backend/routes/audit.py:110` instead declares bounded `limit`, `cursor`, and
`AuditPage`. The driver target does not serve this checkout's contract; its
commit identity is UNVERIFIED. No shared service was replaced or test weakened.

The four Vulture identities are already present at
`quality/vulture-baseline.json:1005,1014,1076,1175`. Production caller
`backend/services/audit_bridge.py:186` invokes the retained `get_page` port.
Deleting these live APIs or appending duplicate ledger rows would not repair
trusted-base authorization. Candidate ledger already matches the scan; no
amendment is justified. A separately landed grant is required by the gate;
this worker must not edit grants or mutate GitHub.

Additional fresh validation passed:

- `uv run ruff check .`
- `uv run ruff format --check .` (2861 files)
- `uv run python scripts/check-api-route-contracts.py` (281 handlers)
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` (3352)
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` (12486)
- `git diff --check`

Both supplied commits resolved; the vulture gate independently selected trusted
base `1e4933e2a1b7`, which is recorded rather than overridden to force a pass.
A requested adjacent `tests/e2e/conftest.py` read returned not found; skipped.
No new tests were added, so inventory delta is zero.

## Acceptance matrix

| Criterion | Executed evidence / residual gap |
| --- | --- |
| Bounded cursor pagination, stable ordering, max page | 76 backend and 8 core tests pass; reachable route delegates to tested page adapters. Driver deployment remains stale. |
| Authorization/scope before database pagination | Scope/isolation and SQL predicate tests pass; admin decision-audit restriction preserved per ADR-073. |
| Frontend incremental loading and virtualization | Source reviewed (`AuditLog.tsx`: cursor loading and viewport slice); browser runtime UNVERIFIED this round. |
| Filters, export, retention without browser corpus loading | Filter/export/retention declaration tests pass; native download avoids JS corpus accumulation. Operational purge/retention UNVERIFIED, explicitly absent in `audit_query.py:79` and deferred to #325. |
| Measured large-data query/index strategy | Both SQLite million-row tests executed with deterministic VM-work bounds above; PostgreSQL runtime UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, maximum limit, empty pages, million-row envelope | Fresh targeted suites pass for SQLite/memory; four PostgreSQL cases skipped. |
| Corpus-independent initial page cost | Durable SQLite request cost proven after startup indexing. NOT MET for memory fallback (`audit_query.py:402` copies/sorts corpus). |
| Bounded browser memory/DOM | Source caps retained rows at 500 and renders a viewport slice; runtime/heap behavior UNVERIFIED. |

## Handoff

**BLOCKED.** Only this evidence note changed; no speculative production, test,
ledger, authorization, execution-authority, or gate edits. Canonical
Goal -> Graph -> Run -> NodeRun -> Attempt unchanged. Commit locally, never push.

Next inputs: exact-candidate integration producer logs/conclusions, driver
services built from the candidate, and trusted-base authorization for retained
APIs. Acceptance also retains the memory-mode cost and retention gaps above.
Do not repeat this repair with unchanged inputs expecting different gate results.

Progress: {checked: 1, done: 0, skipped: 0, errors: 2,
next: external gate inputs and candidate deployment required}.
