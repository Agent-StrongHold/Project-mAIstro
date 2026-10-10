# Issue 358 repair — 724aa2

## Frozen scope

- Assigned issue: #358 only; supplied PR #1712 is evidence, not mutation authority.
- Worktree `/home/dev/Git/wt/auto-358`, branch `auto-358`.
- Starting HEAD `90c1f54b59cb65bf283f15f0c01672225ef4fa9a`; supplied base
  `c560d4ccad82f2bb43b73cbf80e3d1eb5dba5250`; both resolve. Initial tree clean.
- Process only supplied audit pagination implementation/test files, relevant
  authorization dependencies, integration-scope gate and vulture identity evidence.
  No unrelated repairs or gate weakening.
- Driver check-3 fails at `test_pm_workflow_api.py:271` (200 != 403);
  check-6 requests an unregistered inventory suite. Backend driver tests pass
  77 cases; these are observations, not acceptance proof for this round.
- Assumption: writer repair role applies. Investigate current policy before
  changing the failing test; historical notes are not authoritative.

## Results

- Executed requested Vulture scan: FAIL, 1,346 findings vs 1,342 trusted
  identities. Four `get_page` methods are already banked in the candidate;
  the gate explicitly requires trusted-base authorization. Production caller
  `backend/services/audit_bridge.py:186` uses this protocol. No dead-code
  deletion, rename, duplicate ledger row, or gate amendment is justified.
- Read accepted ADR-068, ADR-073 and ADR-081226-69ee. Sentinel decisions remain
  admin-only; do not change the failing workflow assertion to accept 200.
  Canonical Goal/Graph/Run/NodeRun/Attempt authority remains unchanged.
- Integration-scope is a specialized-check aggregator, not a source scanner.
  Its candidate-specific evidence must be distinguished from historical PR
  evidence. Replay of the supplied latest-by-ID check results passes the real
  checker, but those nine successful producers and successful aggregator belong
  to `84081fba82fc9a0aa386af6a8cc1b093b0997de2`, not this assigned HEAD.
  No GitHub refresh, fabricated results, or gate changes were performed.

## Focused validation executed

Logs with the `repair-` prefix are in the supplied job directory
`/home/dev/maistro/jobs/724aa223c1d543e7972433f7924c2190/`.

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | Pass |
| `uv run ruff format --check .` | Pass, 2,977 files |
| `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_noop_route_contracts.py -x -q -s` | 77 passed; `repair-backend.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_audit_pages.py packages/maistro-core/tests/workspaces/test_store_boundary_scope_conformance.py -x -q -s` | 45 passed, 4 PostgreSQL cases skipped; `repair-core.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Fail: four identities require trusted-base authorization; `repair-vulture.log` |
| `uv run python scripts/check-integration-scope.py --event-name pull_request` with captured `--result NAME=success` arguments | Pass for captured PR HEAD only; exact arguments/IDs in `repair-integration.log` |
| `node --test tests/ci/integration-scope.test.cjs` | 12 passed; `repair-integration-tests.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e --suite packages/maistro-core/tests` | Pass: 3,393 / 23 / 13,738; the driver's `packages/hive-conductor/tests` is not a registered recipe |
| `npm --prefix packages/hive-conductor/frontend run build` | Pass; `repair-build.log`; not browser runtime evidence |
| `DOCKER_HOST=unix:///var/run/docker.sock docker ps --format '{{.Names}} {{.Ports}}'` | Fail: cannot connect to daemon |

Read the driver's `check-3.log`: the configured external target returns 200
where independent health selects canonical/admin-only 403. Its deployed
revision is unproven; the local convergence test executes the app with a real
SQLite Container and verifies 403. This does not justify weakening either
assertion or declaring the external E2E failure repaired.

## Acceptance assessment

| Issue criterion | Fresh evidence / unresolved portion |
| --- | --- |
| Bounded cursor pagination, stable ordering and maximum size | Passing local route/adapter tests cover keyset ties, clamps, malformed cursors and empty pages. PostgreSQL runtime UNVERIFIED. |
| Authorization/scope before database pagination | Passing real SQLite scope/filter tests and app convergence tests; route checks core authorization before reads, SQL scopes each seek before LIMIT. External E2E authorization remains unresolved. |
| Incremental frontend loading and virtualization | Inspected production `AuditLog.tsx` cursor loading, observer rearming, stale-response generation guard and viewport slice. Build passes. Browser runtime UNVERIFIED. |
| Filters/export/retention avoid loading full corpus into browser | Passing filter, lazy capped export and retention-contract tests. Export is a direct NDJSON download; retention reports constants, explicitly no purge. Retention lifecycle is UNVERIFIED and belongs to #325; not claimed implemented here. |
| Measured representative large-dataset index/query strategy | Fresh million-row legacy SQLite index build 9.452s; first page 0.0006s; scoped page 0.0003s; maximum query work <2,800 VM instructions. Canonical SQLite load 8.779s; maximum query work 3,400 VM instructions. PostgreSQL envelope UNVERIFIED. |
| Tests for inserts, cursor stability, isolation, max, empty and million rows | Executed focused suites: 122 passed, 4 skipped. Cases use real adapters/SQL, including concurrent inserts. |
| Initial page cost independent of corpus size | NOT MET for reachable unbound memory path. Fresh counted-mapping probe of production `page_entries(limit=1)` visits 100/100 and 10,000/10,000 entries (`repair-memory-ledger.log`). `audit_query.py:386` sorts the whole mapping; durable SQL work is bounded. |
| Browser memory/DOM bounded | Source caps retained entries at 500 and mounts a viewport slice; adjacent Playwright tests assert <=30 mounted rows over eight pages. Browser execution here UNVERIFIED. |

## Handoff

**BLOCKED.** No safe named-gate repair is established: candidate ledger already
contains exactly the four reviewed live pagination identities, and adding
copies cannot create trusted-base authorization. A reviewed grant must land
through the authorized workflow before this retained API debt can pass. No
ledger or grant files changed. Do not repeat identical rebanking attempts.

Candidate-specific integration producer evidence is still needed; the supplied
historical failure label conflicts with the captured successful older check
runs. An available test stack is needed for PostgreSQL/browser validation.
The memory fallback's corpus-wide sort is a real remaining acceptance gap,
not something a gate-only change could remedy.

Only this evidence/handoff file changed in this round. No test additions or
changes, so no inventory delta is required. Existing implementation and prior
notes preserved; no remote mutation or destructive Git command performed.

Progress: checked 1 issue; done 0 complete repairs; skipped 0 issues;
errors 1 unresolved named gate (Vulture). Next: authorized trusted-base grant,
resolve external target provenance, then memory-path and missing runtime
acceptance work. Local commit records this partial handoff, not approval.
