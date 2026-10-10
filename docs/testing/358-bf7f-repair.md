# Issue 358 repair — bf7f

## Frozen scope and entry

Issue #358 only, worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
Starting HEAD `f54ccb30d02dd7b4d9b1d7e1e7642ea6e2b02031`, supplied base
`34795962548a33f6b6f7e1234dcea201a9df96ef`. Initial worktree clean; preserve
all existing branch history. No merge conflict exists, so no moving-base sync.
Inputs: supplied dispatch-context.json, check-0 through check-7 logs, previous
cb9d result. Candidate scope: existing audit implementation, its adjacent tests,
an inventory note if tests change, this report. Gates are validation-only; ledger
amendment only if the requested exact scan demonstrates reviewed retained debt.

## Evidence checkpoint

- Exact requested vulture scan passed: 1,328 reviewed identities, 1,328 findings,
  zero unclassified. No ledger amendment justified.
- Driver check-3 failed against an HTTP server returning the old array contract;
  do not relax the canonical audit authorization assertion to accept it.
- Driver check-6 requested an unregistered suite; use the registered E2E recipe.
- Docker daemon is unavailable: `DOCKER_HOST=unix:///var/run/docker.sock docker
  version --format '{{.Server.Version}}'` failed to connect. Browser/PostgreSQL
  execution requiring that daemon is not proven.
- Integration-scope workflow aggregates exact-candidate producer results; no
  failing producer log is supplied. A passing historical SHA cannot prove this
  head. Gate policy must not be changed to manufacture success.
- Current legacy memory query sorts `store.items()` per request, so the prior
  bounded-initial-page concern is real and needs storage-boundary inspection.
- Read ADR-037/068/073 and ExecutionRuntime ADR-081426-1f7c. Keep canonical
  Sentinel audit admin-only, legacy personal actor scoping, indefinite event
  retention (#325 owns purge), and Goal -> Graph -> Run -> NodeRun -> Attempt.
- Storage inspection confirms legacy `JsonStore` returns mutable row aliases;
  a request-side cache is unsafe. Any repair must maintain indexes at mutation
  seams and detach returned records, not infer freshness from corpus length.

## Repair file snapshot

Frozen implementation files after adjacent architecture inspection:
`backend/services/audit_query.py`, `backend/services/model_store.py` (widen only
its backing mapping annotation), `backend/stores.py`, and
`backend/tests/test_audit_pagination.py` under `packages/hive-conductor/`;
`docs/testing/inventory-notes/358-bf7f-memory-index.md` and this report. The indexed
mapping remains the existing legacy JsonStore's backing data, not another audit
authority. Generic JsonStore callers retain their existing behavior.

Second and final integration ambiguity inspection: supplied check-run records
show integration-scope **success** for `bc293cd790b6852da71b3e251dcecdda84bbde9b`,
not the assigned head. Missing failing candidate/producer log is UNRESOLVED;
do not poll GitHub or invent producer results.

## Implementation checkpoint

- Added regression tests first. `uv run pytest packages/hive-conductor/backend/
  tests/test_audit_pagination.py -k production_memory -x -q` failed on the old
  implementation at `store.items()` with "page enumerated the audit corpus".
- Replaced the production legacy audit store's backing mapping with detached
  rows and write-maintained filter indexes. JsonStore still owns persistence;
  only its backing mapping annotation is widened. Every existing mutation seam
  updates that mapping, including initialization and durable conflict adoption.
- Focused audit/convergence/routes/noop run: **84 passed**, including six new
  collected cases and actual SQLite million-row checks. Migration 9.865s;
  initial page 0.0006s; scoped page 0.0004s; max query work <2,800 VM instructions.
- Strengthened memory regressions to reject corpus/index iteration and oversized
  slices, with <64 index probes across sparse/empty/deep queries at both sizes.
  Existing SQLite parity test now compares the actual indexed production type.
- First full backend run stopped after 250 passing tests: the new query-only
  iteration guard also blocked fixture teardown. Repaired the test using a
  scoped monkeypatch context; no production contract was weakened.
- Core/migration suite: 52 passed, 22 skipped (PostgreSQL/service-dependent).
  Canonical SQLite million-row load 10.468s; max work 3,400 VM instructions.
- Ruff check/format, vulture, API route-contract check, TypeScript/Vite build,
  18 Python integration-scope tests and 12 Node aggregator tests passed.
- Full backend rerun: 1,228 passed then failed at
  `test_degraded_mode_surface.py:221`: a fresh FastAPI with the audit router but
  no principal expects 200, actually 401. Authorization is unchanged by this
  round and required by ADR-068/073. This adjacent pre-existing audit assertion
  is outside the frozen repair file list; preserve it and report, not weaken
  the production gate. Remaining full-suite cases were not run.
- Inventory gate passed: backend 3,595 (+6), registered E2E 23, core 15,423.
  Ruff check/format and `git diff --check` passed after the test guard repair.
- Browser validation without Docker: the job-local `audit-browser-probe.cjs`
  bundles the **actual AuditLog component** and drives installed Chromium with
  controlled API replies. After resolving local harness dependency/env wiring,
  assertions passed for eight incremental pages / 800 rows, a 500-row retained
  cap, <=30 mounted rows, cursor order, refresh and filtering. The native export
  link emitted a download event but `download.path` was canceled in the mocked
  transport; download completion remains UNVERIFIED. This is component evidence,
  not authenticated routed E2E, not a live-backend test, and not a heap-byte
  measurement. Artifacts remain in the assigned job directory; no extra
  repository test/suite count was added by this one-off probe.

## Final validation commands

Executed with 600–1,200 second timeouts:

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py -x -q -s
uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py tests/migrations/test_audit_cursor_indexes.py tests/migrations/test_migration_chain.py -x -q -s
uv run pytest packages/hive-conductor/backend/tests -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests
uv run pytest tests/test_check_integration_scope.py -x -q
node --test tests/ci/integration-scope.test.cjs
uv run python scripts/check-integration-scope.py --event-name pull_request --required-json
uv run python scripts/check-api-route-contracts.py
npm --prefix packages/hive-conductor/frontend run build
node /home/dev/maistro/jobs/bf7f2b8f8bcf4679bdfa776fdc7a40b3/audit-browser-probe.cjs
git diff --check
```

Final focused run: **90 passed** in 23.24s, including acknowledged-write tests.
Latest million-row legacy SQLite migration: 9.829s; initial page 0.0007s;
scoped page 0.0004s; query work <2,800 VM instructions. Full backend run and
browser probe limitations are recorded above, not counted as passing commands.
All other commands passed (core/migration has 22 skips). Integration-scope's
`--required-json` resolves nine producers; it does **not** certify their success.
No ledger/grant/workflow changes, no guessed scanner repairs, no GitHub writes.

## Acceptance matrix

| Criterion | Executed evidence / limitation |
| --- | --- |
| Bounded cursor pagination, stable order, maximum size | 90 focused backend + 52 core/migration tests passed, including ties, cursor continuation, limit clamping and empty pages. |
| Authorization/scope before database pagination | SQLite scoped/filter query work bounds and canonical deny-before-query tests passed. ADR-073 admin-only canonical decisions preserved. PostgreSQL runtime UNVERIFIED. |
| Incremental loading and virtualization | Chromium actual-component probe passed eight pages/800 rows and <=30 mounted rows; build passed. Authenticated routed E2E UNVERIFIED. |
| Filters/export/retention without browser corpus | Backend filter and bounded NDJSON export tests passed; browser filter/reset and export URL assertions passed. Native download completion UNVERIFIED. ADR-037 indefinite event retention retained; #325 owns purge. |
| Measured representative large data/index strategy | Two actual million-row SQLite tests passed with deterministic VM-work bounds. New memory tests reject corpus/index walks and full slices at 100 and 10,000 rows. PostgreSQL performance UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, maximum/empty pages, million-row envelope | Executed backend/core tests passed, including threaded production-memory inserts, acknowledged durable writes and sparse scopes. |
| Initial page independent of corpus | Repaired production legacy-memory path now seeks write-maintained indexes; structural probes reject scans. Durable paths retain measured indexed seeks. Plain unindexed mappings remain a compatibility-only O(n log n) path, not the production binding. |
| Browser memory/DOM bounded | Component probe verifies 500 retained rows and <=30 mounted rows after 800 loaded. No full-app heap-byte measurement or routed live-server proof. |

## Handoff — BLOCKED

Changed files: `backend/services/audit_query.py`, `backend/services/model_store.py`,
`backend/stores.py`, `backend/tests/test_audit_pagination.py` (under
`packages/hive-conductor/`), this report, and
`docs/testing/inventory-notes/358-bf7f-memory-index.md` (+6).

The actual storage defect is repaired and locally validated. Remaining blockers:

1. Supply the failing merge-group candidate SHA and producer log. The dispatch
   contains only a successful integration-scope result on another head.
2. Point driver API checks at this candidate rather than the old array-contract
   service; use the registered `packages/hive-conductor/tests/e2e` inventory key.
3. Provide PostgreSQL/isolated live E2E infrastructure; Docker is unavailable.
4. Reconcile `test_degraded_mode_surface.py:221` with authenticated audit reads
   in a separately scoped repair; never make the route anonymous to satisfy it.
5. Complete native browser download and live routed E2E validation.

Residual tradeoffs: detached reads intentionally disallow mutation via aliases
(use JsonStore assignment); eight filter indexes consume extra server memory and
out-of-order replacement/deletion can shift index lists. This is not a new audit,
authorization, scheduling or execution authority. Existing branch history and
unrelated diffs were preserved. Commit is a repair handoff, not integration approval.

Progress: checked 1 issue; done 1 concrete repair; skipped 0 issues; errors 3
remaining validation blockers (full-suite assertion, native download probe,
Docker daemon). Integration-scope's missing exact-candidate evidence remains
UNRESOLVED. Next: the five explicit handoff actions above, not another blind
ledger change or repeated validation against the mismatched service.
