# Issue #358 repair checkpoint

Scope frozen: issue #358 only, starting HEAD 3201d8c10f3eba498395a6c2b2213b9652d2010f,
base 8a4bc239fe9af429be9faa087916f965e9fb20f7. Clean worktree at entry.
Process the supplied integration-scope and vulture failures; inspect existing audit
routes/query service, core audit paging, frontend AuditLog, adjacent tests and CI
configuration. No unrelated repair, GitHub mutations, or gate weakening.

Initial evidence: supplied check-3.log failed at test_pm_workflow_api.py:271:
MaistroCoreBridge health but legacy unbounded list response to /v1/audit?limit=1.
check-6.log used an unsupported inventory suite (packages/hive-conductor/tests).
Other supplied checks passed. Assumption to verify: external live service may not
be built from this branch. Do not accommodate stale behavior in assertions.

Exact Vulture command executed: exit 1; no unbanked candidate identities,
1343 findings vs 1339 trusted-base identities. Four `get_page` APIs are already
banked in the candidate but not authorized by the trusted base (35f2e0158a91).
Investigate the production call seam before deciding whether this is removable
scanner debt; do not add grants or fabricate integration producer outcomes.
ADR-073 requires canonical Sentinel decision reads to remain admin-only.
Production `services/audit_bridge.py:185` already calls `audit_log.get_page`
directly. Vulture scans only packages/*/src, excluding that real consumer.
Deleting or renaming these retained APIs just to satisfy the scanner is not a
behavioral repair. Candidate ledger already contains all four exact identities.

Integration required-json command succeeded, requiring nine producer checks.
Initial dispatch extraction encountered a list rather than dictionary for
check-runs; correct the local parser once, without refetching. Guessed e2e
conftest/playwright paths were not found; skipped in favor of file discovery.

Focused validation rerun (not inherited claims):
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 2913 files.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: 76 passed.
  Million-row legacy SQLite: index migration 10.508s (startup), first page
  0.0010s, scoped page 0.0004s, maximum query work <2800 VM instructions.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: 45 passed, 4 PostgreSQL cases skipped (no configured DSN).
  Million-row canonical SQLite: load 9.457s, maximum query work 3400 instructions.

Captured integration evidence is for linked PR head 3a9865527991, NOT local
HEAD. It records hive e2e/UI, wheel, docker, durable-events, object storage,
strike-ladder and postgres producers skipped, integration-scope failed.
No producer evidence for local HEAD is supplied. Changing this aggregator
would conceal missing evidence, not repair the assigned feature.

## Final acceptance / handoff

- Bounded stable cursor pages: proven on current source by the 121 passing
  focused tests, including maximum limit, empty pages, ties, concurrent inserts,
  malformed cursors and route-level envelopes.
- Authorization/scope before database pagination: exercised in legacy durable
  SQLite and canonical SQLite, with admin-only canonical HTTP reads in
  `test_audit_convergence.py`. ADR-073 takes precedence over personal access to
  canonical decision records; the legacy unbound fallback is actor-scoped.
- Incremental frontend loading/virtualization: source inspected; `npm run build`
  in `packages/hive-conductor/frontend` passed. Browser execution, DOM and heap
  bounds remain UNVERIFIED in this attempt. Do not equate build with UI proof.
- Filters/export: scoped, capped, streaming backend tests at
  `test_audit_pagination.py:455-491` passed. Retention metadata tests passed;
  operational purge is absent (`audit_query.py` explicitly delegates to #325).
  Browser download and operational retention remain UNVERIFIED.
- Representative query/index strategy: both SQLite million-row envelopes passed
  with deterministic VM-work bounds above. PostgreSQL execution remains
  UNVERIFIED (four skips); no shared database was truncated to obtain evidence.
- Initial page cost independent of corpus: measured for durable SQLite only.
  Legacy memory fallback still sorts the full corpus per request
  (`audit_query.py:_sorted_ascending`); canonical memory scans it as well.
  The unconditional definition of done is therefore not established.

Additional executed checks:
- `uv run python scripts/check-integration-scope.py --event-name pull_request`:
  exit 1, all nine producer outcomes missing locally. This is an evidence
  prerequisite, not proof of nine code defects. No outcomes were fabricated.
- Read-only GET `http://localhost:8101/openapi.json`: /v1/audit response is an
  array, query fields are action/severity/actor only, /v1/audit/export absent.
  Thus the driver's live API check targeted a different build. Current branch
  declares AuditPage, limit/cursor, and export; assertions must not be weakened
  to match the external service. Run the e2e suite against a branch-built service.
- Inventory gates for `packages/hive-conductor/backend/tests` and
  `packages/maistro-core/tests`: pass (3385 and 13064 identities respectively).
  The driver's `packages/hive-conductor/tests` recipe is not registered; correcting
  that driver invocation is outside this worktree's assigned feature repair.
- `git diff --check`: pass.

No production/test/ledger edits were justified by the named failures. Existing
ledger rows are already exactly reconciled with the scan; an extra amendment
would invent debt. A separately landed trusted authorization is required for
these four reviewed retained APIs; this worker may not edit grants or integrate.
Only this evidence document changed. No tests were added, hence no inventory
delta. No GitHub mutations or background servers were used.

Outcome: BLOCKED. Snapshot progress: checked 1, done 0, skipped 0, errors 1
(unresolved gate prerequisites). Next owner must supply trusted-base Vulture
authorization and same-candidate producer outcomes, and provision an isolated
branch-built browser/API target before claiming full acceptance.
