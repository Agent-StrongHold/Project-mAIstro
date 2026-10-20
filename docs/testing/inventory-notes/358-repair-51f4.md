---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — job 51f4

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`995ef3ab0c8063a8217573808e65a87682b544d3`, supplied develop base
`4010e69f62cfb3ffa86e68b12341e7c3a95a77cb`. Initial worktree clean.
Files in scope: the existing #358 audit routes/query/store/page/UI/migration
and adjacent audit/e2e tests, the named integration-scope workflow/harness,
`quality/vulture-baseline.json` (explicit repair permission), and this note.
No unrelated issues or remote mutations.

## Initial evidence and assumptions

Driver logs check-0/1/2 pass dependency sync/lint/format; check-4 reports 76
passing focused tests; check-5/7 inventory passes. check-6 uses an unsupported
inventory suite (`packages/hive-conductor/tests`). check-3 fails at
`test_pm_workflow_api.py:271`: live endpoint returns a bare unbounded array,
not the expected canonical 403 or stub cursor page. Prior result confirms
that same failure. Earlier notes claim a stale shared service and ungranted
vulture identities; neither claim is accepted without fresh validation.
Assumption: reproduce using the checked-in CI harness rather than modify
shared services or relax authorization assertions. Integration-scope is an
aggregate gate; inspect its producers before choosing a repair.

## Validation and outcome

Fresh exact vulture scan (exit 1, `/tmp/358-51f4-vulture.log`) finds 1346
identities against trusted base `91996e19223d` (1342). Four retained
`get_page` methods are already banked at `quality/vulture-baseline.json`
lines 1004, 1013, 1075, 1174; the actual live caller is
`backend/services/audit_bridge.py:186`. No genuinely dead code or missing
candidate ledger rows were found. Gate explicitly requires a trusted-base
grant, not another candidate ledger edit. No ledger/grant mutation justified.

Read ADR-073: canonical decision audit must remain admin-only. The branch
route enforces that before reads and returns AuditPage for legacy reads;
no branch list path returns the bare array in check-3. Read integration-scope
workflow: aggregate of specialized producers, not a standalone pytest job.
Fresh `ruff check .` and `ruff format --check .` pass. Focused backend audit
pagination/routes/convergence: **61 passed** in 28.10s. Million-row legacy
SQLite measurements: indexes 12.834s, initial page 0.0007s, scoped page
0.0004s, maximum query work <2800 VM instructions.

CI-exact compose API command with isolated project `audit358-51f4` built both
images successfully but failed before startup: Docker default network pools
exhausted (`/tmp/358-51f4-compose-api.log`). Inspected existing networks once;
none use 10.234.58.0/24. Retry will use that explicit subnet (only environment
override; no application/test changes). All nine integration-scope producers
are required for a PR; aggregate success cannot be inferred from these
focused local checks.

Second startup attempt reached the explicit network but failed on occupied
port 8101; final override also resets published ports to `[]`. Internal
`HIVE_BASE_URL=http://hive:8101` remains unchanged. CI compose API producer
then **10 passed, 13 skipped**, including the exact failing audit test, against
images freshly built from this worktree. Evidence:
`/tmp/358-51f4-compose-api-isolated.log`. Shared service left untouched.

Fresh dedicated `pgvector/pgvector:pg18` container `audit358-51f4-pg`, dynamic
loopback port, migrated with `uv run alembic upgrade head`: success. Core
`test_audit_pages.py` plus `test_store_boundary_scope_conformance.py`:
**66 passed, no skips** (68s). SQLite canonical million-row max 3400 VM
instructions, load 12.513s; PostgreSQL canonical million-row maximum 54
shared blocks (bound <500). `/tmp/358-51f4-core.log`.

Migration single-head gate: **3 passed**. Inventory gate using the three
actual suite keys: **3385 backend, 23 API e2e, 12811 core**, all match.
No test additions or test assertion changes.

UI compose producer with `CI=true`, same isolation overrides and freshly built
images: **119 passed, 1 failed, 5 did not run** in 4m. All five audit cases
passed (authority, two late-response filters, short-page incremental loading,
500-entry/30-row bounds). Actual failure outside #358:
`tests/e2e/rsi-polling-resilience.spec.ts:478` expected 4 request starts, got 3
after 15000ms. `/tmp/358-51f4-compose-ui.log:338-355`. Not dismissed as flaky,
not changed, and not retried to obtain a green verdict. This required producer
means integration-scope remains blocked. Doc links: 0 broken.

## Acceptance assessment (fresh evidence, not inherited claims)

- Bounded stable cursor/max page: 61 backend and 66 core tests pass; deployed
  compose API audit test passes. Limits clamp to 200; row identity breaks ties.
- Authorization before database pagination: real SQLite/PG scoped filter tests
  pass; canonical route convergence tests prove ADR-073 admin-only enforcement.
  Legacy personal actor scope is not an alternate Sentinel authorization path.
- Incremental loading and virtualization: all five audit Playwright cases pass,
  including 8 pages with at most 500 retained entries and 30 mounted rows.
- Filters/export: backend streaming/cap/scope tests and browser filter/export
  link tests pass. Retention metadata is bounded and honestly reports no purge.
  Actual retention deletion remains UNVERIFIED/unimplemented here (#325).
- Representative million-row query/index measurements: legacy SQLite <2800 VM
  instructions; canonical SQLite 3400 VM instructions; canonical PG18 max 54
  shared blocks, including filtered and deep-tie cursors.
- Concurrency/cursor/scope/max/empty/million-row test coverage executed in both
  focused suites, including PostgreSQL (no core skips).
- Initial page cost independent of corpus: proven for indexed durable queries,
  NOT universal: `backend/services/audit_query.py::_sorted_ascending` sorts the
  full in-memory corpus per request. Do not claim unconditional completion.
- Browser memory/DOM row count: bounded entry window and mounted-row assertions
  passed; byte-level heap profiling is not claimed.

## Handoff

**BLOCKED, not an integration approval.** No evidence justifies changing audit
production code to fix the supplied stale-target result. The retained vulture
identities need a separately landed trusted-base authorization, which this
worker cannot grant. Integration-scope also has the fresh unrelated RSI UI
failure above; remaining specialized producers have not all been rerun.
`uv run python scripts/check-integration-scope.py --event-name pull_request
--result 'hive-conductor-e2e=success' --result 'hive-conductor-e2e-ui=failure'`
exits 1: failed UI producer and seven missing complete producer results (the
focused PG18 test is not the full postgres job). Final ruff lint/format and
`git diff --check` pass. This job's hive and PostgreSQL containers are stopped;
container/log evidence is preserved, and no other lane's services were changed.

Only this evidence/inventory note is changed; no ledger edit is needed because
all four retained identities are already present. No remote actions, gate
weakening, test skips, or competing execution/audit authorities introduced.

Progress: checked 1 assigned item, done 0 repairs, skipped 0, blocked 1.
Next: maintainer resolves trusted-base grant and routes RSI failure to its
owner; driver must target a freshly built branch service, not shared port 8101.

