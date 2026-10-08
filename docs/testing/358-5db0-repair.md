# Issue #358 repair — job 5db0f385

## Frozen scope and salvage

Assigned issue #358 only, branch `auto-358`, initial HEAD
`5959cd973bbd4853aac7f8376c6a2ea15a0df78c`, base
`d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`.
The worktree arrived mid-merge from that exact base, with staged develop
changes and one conflict in the capability migration chain test. Both incoming
index and worktree diffs are preserved in the job directory as
`incoming-358-index.patch` and `incoming-358-worktree.patch`.
Assumption: finish this pinned merge, not fetch a moving base. No unrelated
issues, GitHub mutations, discarded work, or policy/gate weakening.

Read repository instructions, accepted ADR-073 (canonical audit is admin-only)
and ADR-081226-9944 (canonical ownership/execution hierarchy), supplied issue
body, driver logs, and previous result/handoff. Pagination remains a read
projection; no execution/event/authorization authority is introduced.

## Actual evidence at entry

- Driver check-1/check-2 fail on unresolved conflict markers.
- Both `061_audit_cursor_indexes.py` and landed
  `061_hitl_pause_kind_index.py` claim revision `061` on `060`. Only the
  unlanded audit migration must move to `062`, preserving landed history.
- Develop removed obsolete effect migrations 043/045 and folded schema into
  035. Preserve that resolution and retain audit chain assertions after 061.
- Driver check-3 sees canonical health but a legacy list response from the
  external HTTP service. This does not prove that service runs this candidate.
  Do not relax admin-only or pagination assertions to accept it.
- Driver check-6 names unregistered inventory suite
  `packages/hive-conductor/tests`; the registered suite is `tests/e2e` under
  that package.
- The supplied prior handoff reports missing failed-candidate producer evidence
  for integration-scope. Re-evaluate locally without fabricating successes.

## Executed validation checkpoint

- Regression before renumber: migration chain test failed with duplicate heads
  `['061', '061']` (worker-migration-red.log). After repair: 4 passed,
  18 live-database tests skipped (worker-migrations.log).
- `uv run ruff check .` and `uv run ruff format --check .`: pass,
  3,196 files formatted.
- Exact requested Vulture scan: pass, 1,326 findings, zero unclassified.
  No additional ledger amendment is warranted. Incoming merged ledger equals
  the pinned develop base (`git diff --numstat <base> -- quality/` empty).
- Focused five backend modules: 91 passed. Million-row startup index build
  10.023s; initial page 0.0009s; scoped page 0.0004s; maximum work <2,800
  SQLite VM instructions (worker-backend.log).
- Core audit pages and workspace boundary conformance: 50 passed, 4 PostgreSQL
  cases skipped. Canonical SQLite million-row load 8.803s; maximum query work
  3,400 VM instructions (worker-core.log).
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps ...`: cannot connect to
  daemon. Live PostgreSQL validation unavailable in the advertised environment.
- `uv run python scripts/check-integration-scope.py --event-name merge_group`:
  fails closed for nine missing producer results, not a reproduction of the
  unknown remote failure. Snapshot contains only integration-scope success on
  `bc293cd790b6852da71b3e251dcecdda84bbde9b`, not a failed candidate/log.
  Do not fabricate producer successes or modify the aggregator.

The migration round-trip now downgrades only audit revision 062 to its actual
parent 061 and checks the landed HITL column/index survive. No test count change.
## Final focused validation

- Repeated Ruff checks after all edits: pass (3,196 files).
- Repeated migration selection after round-trip update: 4 passed, 18 skipped;
  `uv run alembic heads`: exactly `062 (head)`.
- `uv run pytest tests/test_check_integration_scope.py
  tests/test_pr_scope_policy_parity.py tests/test_ci_merge_group_scope.py -x -q`:
  53 passed. These prove gate logic, not missing candidate producer evidence.
- `uv run python scripts/check-api-route-contracts.py`: pass, 284 handlers,
  15 audited routes, zero canned responses.
- `uv run python scripts/check-suite-inventory.py --suite tests/
  --suite packages/hive-conductor/tests/e2e`: pass, 5,045 and 23 tests.
  The registered E2E suite path resolves the driver check-6 invocation error;
  no inventory baseline or gate weakening was needed.
- `cd packages/hive-conductor/frontend && npm run build`: pass, TypeScript
  checks and Vite production build. Build outputs are ignored, not committed.
- `git diff --check`: pass. Pre-commit `git diff --cached --check` additionally
  reports trailing blank lines in two incoming develop documents
  (`docs/issue-42-ci-repair.md:144` and
  `docs/testing/inventory-notes/1109-hitl-pending-fairness.md:288`). They are
  unchanged from the pinned base and retained, not cosmetically edited by this
  lane. This interrupted the chained commit command; commit was retried
  explicitly after recording the inherited warnings.

## Acceptance and residual risks

| Criterion | Executed evidence / explicit limit |
| --- | --- |
| Bounded cursor, stable ordering, maximum page size | 91 backend and 50 core/boundary tests passed; route and real SQLite/memory adapters cover ties, floors/ceilings, malformed cursors. |
| Authorization/scope before database pagination | Admin denial-before-query, actor isolation, exact org filters and SQL seek tests passed; production route/bridge/query inspected. ADR-073 admin-only decisions take priority over personal legacy semantics. |
| Incremental loading and virtualization | Production component and routed browser tests inspected; frontend build passed. Browser execution **UNVERIFIED** this round. |
| Filters/export/retention without whole-corpus browser loading | Filtered/scoped lazy capped NDJSON and retention endpoint tests passed. Production UI uses a native download link and retains at most 500 rows. Native download execution **UNVERIFIED**; purging remains explicitly absent and owned by #325. |
| Measured large-data query/index strategy | Two real SQLite million-row tests passed, measuring bounded VM work separately from startup index cost. PostgreSQL million-row envelope **UNVERIFIED** (daemon unavailable). |
| Concurrent inserts, stable cursors, scope isolation, max limit, empty pages, million-row envelope | SQLite/memory tests passed. PostgreSQL cases skipped. |
| Initial-page cost independent of corpus size | SQLite query-work ceilings passed; indexed memory tests prohibit corpus enumeration and bound reads. |
| Bounded browser memory/DOM rows | Sliding 500-row window and row slicing inspected; existing eight-page/30-mounted-row browser test inspected, not executed. **UNVERIFIED** runtime browser evidence. |

Changed by this repair: rename/reparent audit migration 061 -> 062; resolve
capability migration-chain test without reviving obsolete migrations; update
existing audit DDL and live round-trip tests; this report and zero-delta inventory
note. All other incoming staged files are preserved develop-merge work, not new
feature edits. The merged Vulture ledger already passes; no new identity edits.

Disposition: **BLOCKED**, despite completed local migration repair. Need exact
failed merge-group SHA and producer logs for integration-scope. Its local
missing-results diagnostic is not proof of a remote gate bug. Also need a known
candidate deployment for browser/API E2E and a PostgreSQL service for live
migration/query validation. Do not loosen assertions to match the externally
running service's stale audit contract. No integration approval, push, or issue
closure action.

Progress: checked 1 issue; done 1 migration/merge repair; skipped 0 issues;
errors 1 unresolved integration-evidence blocker; next: obtain failed-candidate
producer evidence and run live PostgreSQL/browser acceptance.
