# Issue 358 repair — job 450db8

## Frozen scope

- Assigned issue: #358 only; branch `auto-358`, clean starting HEAD
  `ea715a617a48cd3530e91f63c78339dc2ffafc73`.
- Dispatch base: `626683154ce9dbd521e6754cee494190c0fb29f0`.
- Process supplied integration-scope failure, exact vulture scan, and issue 358
  acceptance validation. No GitHub mutations or unrelated feature changes.
- File scope: existing audit pagination implementation/tests, migration,
  vulture ledger if actual scan evidence requires it, and this report.
  Any merge reconciliation will preserve both branches' work.
- Supplied check logs inspected: ruff check/format passed; check-3 failed at
  `test_pm_workflow_api.py:198` (live `/v1/dag-runs` returned 500);
  check-4 reports 78 passes; check-5/7 inventory passed; check-6 names an
  unregistered suite (`packages/hive-conductor/tests`). These are historical
  evidence, not acceptance proof for this round.
- Ambiguity: integration-scope failure details are not in check logs. Inspect
  the frozen dispatch evidence and local workflow before selecting a repair.

## Results

### Gate evidence and repair decision

- Exact requested Vulture command reproduced failure: 1,340 findings; four
  `get_page` methods are already banked but absent from the trusted base.
  Inspection confirms the real caller is `services/audit_bridge.py:186`, outside
  CI's `packages/*/src` scan. These are used APIs, not dead methods. Candidate
  ledger additions cannot authorize new debt.
- Existing `packages/maistro-core/src/_vulture_whitelist.py` explicitly references
  external Hive consumers (e.g. `ScopedRunReader.get_runs`). Apply the same
  established scanner-reference convention to the audit protocol and adapters,
  with the real callsite documented, and remove only the four eliminated
  findings from the ledger. No authorization/grant or scan-rule changes.
  This file is added to the frozen repair scope solely for these actual findings.
- Supplied integration check runs all concern `84081fba82fc`, not the assigned
  HEAD, and show success. The workflow requires same-candidate producer results;
  it does not diagnose the claimed later merge-queue failure. Mark that failure
  UNRESOLVED; do not fetch or invent a new check-run list.
- Local `origin/develop` resolves to the dispatch base; no merge conflict exists
  in this worktree. A two-dot base diff includes unrelated newer develop work;
  it is not evidence of deleted feature work on this branch.
- Prior-result inspection confirms unresolved legacy ephemeral page complexity
  and missing runtime browser evidence. Independently validate acceptance below.
- Attempted ADR filename `ADR-073-sentinel-agent-security-layer.md` was not found;
  skip that nonexistent name and read the resolved `ADR-073-warden-sentinel.md`.

### First validation checkpoint

- Read ADR-073, ADR-081226-69ee and ADR-081226-7248. Canonical decision audit
  remains admin-only; no competing authority or execution model is introduced.
- Scanner-reference repair applied; exact Vulture gate now PASS: 1,336 findings
  match 1,336 trusted identities. Only the four observed false positives were
  removed from the candidate ledger; all duplicates and other rows preserved.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,006 files).
- Focused Hive audit/convergence/noop suite: 78 passed (18.24s). Legacy SQLite
  million-row index build 8.390s; initial page 0.0007s; scoped page 0.0004s;
  maximum query work <2,800 VM instructions.
- Focused core audit/pages/scope suite: 76 passed, 5 skipped (10.14s). Canonical
  SQLite million-row load 7.994s; maximum query work 3,400 VM instructions.
  PostgreSQL tests skipped because no test DSN is set. Docker at the prescribed
  socket is unavailable (`docker info` could not connect); do not claim PG proof.
- No runtime code or tests changed: the existing HTTP tests execute the external
  caller and SQLite/in-memory adapters retained by the scanner references.

### Acceptance/environment checkpoint

- Integration-scope CLI without producer results fails closed for all nine
  required checks. Its 12 aggregator unit tests pass, but do not supply the
  missing same-candidate producer evidence. This remains UNRESOLVED.
- Audit migration tests: 2 passed. Suite inventory passes for all three actual
  registered suites (core 13,944; Hive backend 3,456; Hive API e2e 23).
- Frontend production build passes. First browser attempt ran four audit specs
  against the default service on port 8101: all failed before audit rows loaded.
  Evidence identifies **stale served assets**, not candidate component failure:
  `/audit` serves `index-Nkea3ta9.js` last modified October 3, whereas this build
  emits `index-lUGMvdF9.js`. The screenshot describes the old `0 entries` UI,
  not the candidate's `retained locally` page. Next run must serve this worktree's
  build without replacing or stopping the existing service.
- Independent real JsonStore structural probe: a one-row legacy ephemeral page
  calls `_created_at_of` 100 times for 100 rows and 10,000 times for 10,000 rows.
  Corpus-independent initial-page acceptance therefore still FAILS on the
  supported unbound ephemeral fallback. No cache heuristic or alternate audit
  authority is introduced to conceal this defect.

### Candidate browser validation

A job-local Playwright config reuses the existing four audit specs and lets
Playwright own a Vite preview server on port 18158. Vite serves this worktree's
production build and proxies non-mocked API calls to the already-running backend
on 8101. No existing server was stopped/replaced; no gate config was edited.

- `CI=1 NODE_PATH="$PWD/packages/hive-conductor/frontend/node_modules" packages/hive-conductor/frontend/node_modules/.bin/playwright test --config /home/dev/maistro/jobs/450db805c6174d598b4a931622eaa5ee/candidate-playwright.config.cjs pm-workflow.spec.ts --grep '10[b-c] — audit' --retries=0`: **4 passed** (2.4m).
- Executed production routed component with controlled audit responses: both
  stale-response cases, continuously visible load sentinel, eight 100-row pages,
  500 retained entries, at most 30 mounted rows, cursor continuity, filtered
  export link, and refresh back to the first row. These are frontend-component
  proofs, not proof that the older live backend implements this candidate API.
- No new test identities were added for this scanner-only repair; no inventory
  delta is required. Existing meaningful production-path regressions were run.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Stable bounded backend cursors and maximum page size | Hive/core tests PASS, including duplicate timestamp/request IDs, empty pages, floor/ceiling and malformed cursors. |
| Scope applied before database pagination | Authenticated HTTP and SQLite adapter tests PASS; canonical decision audit stays admin-only (ADR-073). PostgreSQL runtime UNVERIFIED (5 skipped tests). |
| Incremental frontend loading and virtualization | Four candidate-build Chromium audit tests PASS. |
| Filters/export/retention without whole-browser corpus | Backend filter/capped streaming export tests and browser filter/export-link tests PASS. Retention metadata is bounded, but reports `corpus_purge: none`; actual purge remains UNVERIFIED, owned by #325. |
| Representative query/index measurements | Both million-row SQLite envelopes executed with deterministic VM-work bounds above; PostgreSQL execution UNVERIFIED. |
| Concurrent inserts, cursor stability, isolation, max limit, empty and million-row coverage | Executed focused backend/core tests PASS on SQLite/in-memory implementations. |
| Initial cost independent of corpus | Durable SQLite and canonical memory seek tests PASS; legacy ephemeral fallback FAILS the independent structural probe. |
| Bounded browser memory/DOM | Browser test verifies the 500-entry retention window and <=30 mounted rows. Byte-level heap bound for arbitrarily large detail payloads is UNVERIFIED. |

## Commands and artifacts

All validation used long (1,000-second) command timeouts. Full round logs are in
`/home/dev/maistro/jobs/450db805c6174d598b4a931622eaa5ee/repair-*.log`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: failed before repair, PASS after repair.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s`: 78 passed.
- `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/persistence/test_sqlite_audit.py packages/maistro-core/tests/persistence/test_pg_audit.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s`: 76 passed, 5 skipped.
- `uv run pytest tests/migrations/test_audit_cursor_indexes.py -x -q`: 2 passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/maistro-core/tests --suite packages/hive-conductor/tests/e2e`: PASS.
- `uv run python scripts/check-integration-scope.py --event-name pull_request`: FAIL (no candidate producer results supplied; not a reproduction of a specific remote failed producer).
- `node --test tests/ci/integration-scope.test.cjs`: 12 passed.
- `npm --prefix packages/hive-conductor/frontend run build`: PASS.
- Browser command above: 4 passed with candidate assets; first default-service attempt failed all 4 against stale assets.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: unavailable daemon.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`: PASS.

## Handoff

**BLOCKED**, not integration approval. Changed only this report, explicit public
API scanner references in `packages/maistro-core/src/_vulture_whitelist.py`, and
four matching finding rows in `quality/vulture-baseline.json`. No production API,
authorization, event authority, execution path, grant or gate rule changed.

The named Vulture repair is complete and locally validated. Remaining work needs
same-candidate integration producer evidence and a mutation-aware solution for the
legacy JsonStore fallback's corpus-dependent page construction; retain all
existing work. PostgreSQL validation needs a reachable test database. Retention
purge is not implemented by this issue's current branch.

Progress: {checked: 1, done: 0, skipped: 0, errors: 2, next: integration evidence and legacy ephemeral page complexity}.
