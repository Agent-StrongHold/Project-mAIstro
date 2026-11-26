# Issue 336 writer review

## Frozen scope

- Issue: #336 only; branch `auto-336`, initial HEAD `ca84d39b7167d0016738fdcea610315285c2010b`.
- Review the existing permission-policy implementation, its consumers, matrix gate,
  adjacent tests, and the issue acceptance evidence. Repair only demonstrated defects.
- Dispatch snapshot: `/home/dev/maistro/jobs/d3b5255c310d4eda9080f2c5006baabf/dispatch-context.json`.
- Existing work is committed and the initial working tree is clean; no salvage patch is needed.
- Prior failure was a provider request error, not evidence that implementation was absent.
  Continue existing work rather than rebuilding it.
- No driver `check-*.log` files are present in the supplied job directory.
- Writer role: local changes and commits are permitted; no remote mutations.

## Progress

- Initial history and diff inspected. Existing implementation includes a canonical
  permission policy, UI elevation handling, matrix gate, and tests.
- Acceptance and validation are being independently checked; previous claims are
  not treated as executed evidence for this round.
- The existing inventory note explicitly lacks the full per-role browser mutation
  walk. The matrix gate currently checks only global string presence, not control
  binding, membership, or elevation recovery. These are acceptance gaps, not proof.
- UI elevation creates synthetic task IDs and never calls task completion or
  revocation. `routes/missions.py` revokes only existing owned missions; synthetic
  UI IDs have no such record. A full elevation-lifecycle repair remains needed.
- Fresh focused validation: `uv run pytest` over `test_permission_policy.py`,
  `test_setup_guard.py`, `test_auth_middleware.py`, and `test_api.py` passed
  (114 tests). The existing task-completion test does not assert the PATCH status,
  so its pass is not sufficient evidence for synthetic browser grant revocation.
- Fresh matrix gate passes (48 API entries, 31 UI mutations), but does not inventory
  `POST /v1/workspaces/default`.
- ADR-092326-7ed7 explicitly requires the default route's `workspaces.write`
  gate. Preserve it: the issue's desired usability does not authorize an exemption.
  Chat uses the canonical resolver directly; the frontend has no default-route
  call site at this head. Do not claim the gated API is a chat blocker.
- Demonstrated reachable defect: `WorkspaceTabs.handleRestore` calls the protected
  PATCH directly, unlike archive in `WorkspaceShare`, and offers no elevation.
  The daily owner cannot restore an archived Workspace in a fresh session.
  Repair that control using the existing canonical elevation provider and add
  browser regression tests. No new execution or authorization authority is needed.
- Root lint and format checks passed before this repair.
- Added four intercepted browser regression cases and a self-contained Playwright
  runner for restore (not a full clean-setup acceptance claim).
- Browser setup initially blocked: `npx playwright install chromium` rejects
  ubuntu26.04-x64; override `ubuntu24.04` also rejects (invalid platform key).
  Resolved with the full key `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64`;
  Chromium downloaded successfully.
- Before the production repair, the new daily-owner browser test failed after
  Restore: `getByRole('dialog', { name: 'Permission elevation' })` never appeared.
  This directly reproduces the reported unreachable flow (not a scanner guess).
- Repair wraps only restore with `useAuthorizedAction` and records the distinct
  restore action in the existing shared inventory. Backend gates are unchanged.
- All four new browser tests pass after the repair; strict TypeScript + Vite
  production build passes. Before/after execution establishes the regression.
- Fresh matrix, route-permission, and principal-identity gates pass. The typed
  client gate fails with 165 problems (trusted-base authorization/candidate ledger
  identities, including pre-existing elevation consumers and the shifted
  WorkspaceTabs type). No ledger/grant edits are permitted in this lane; retain
  this as an explicit integration blocker, not a reason to weaken the gate.
- Full current backend package validation passed: `uv run pytest
  packages/hive-conductor/backend/tests -x -q` -> 3949 passed, 25 skipped,
  31 warnings in 219.12 seconds. Log: `/tmp/auto-336-backend-tests.log`.
  Skips and the package's stubbed engine mean this is not full live-model or
  clean-setup browser acceptance evidence.
- Added four real clean-setup API cases for the repaired action, parametrized
  over owner/editor/viewer/nonmember. Setup provisions the actual daily account;
  no fixture assigns `*` or pre-elevation. The daily owner invites the separate
  admin explicitly, and the latter changes membership through shipped APIs.
  All eight policy tests (four original + four new) pass. The formatter requested
  a layout change in the new parametrized API test; apply then revalidate.
- The initial inventory note's inline empty map was rejected by the parser;
  replaced it with the required indented suite delta, now +4 for the API cases.
- Supplied prior result path is not found; skipped. Dispatch comments contain
  progress markers, not additional technical acceptance evidence.

## Repair completion round (this round, head `ca84d39b71` + salvage)

The previous round died before completing and committing the repair: the
working tree carried the `useAuthorizedAction` import and hook in
`WorkspaceTabs.tsx` but `handleRestore` still called the protected PATCH
directly, plus unformatted test changes and no commit. Salvage was backed up
to `incoming-336-salvage.patch`, then completed:

- `handleRestore` now wraps the PATCH with
  `authorizedAction("workspaces.write", ...)` — the one missing edit.
- Regression proof re-established both ways: with the wrap temporarily
  removed, the new daily-owner intercepted browser test fails exactly as
  documented above (elevation dialog never appears, guaranteed 403 path);
  re-applied, all four intercepted cases pass. `npx tsc -b` + `vite build`
  green.
- `uv run ruff format` reports the backend files clean (the earlier requested
  layout change was already satisfied by the salvaged state); root
  `uv run ruff check .` and `uv run ruff format --check .` pass.
- Targeted policy tests: `test_permission_policy.py` + `test_setup_guard.py`
  + `test_auth_middleware.py` -> 83 passed.
- Full backend package: `uv run pytest packages/hive-conductor/backend/tests
  -x -q` -> **3953 passed, 25 skipped** (+4 = the new parametrized restore
  cases; 3949 was the pre-change count).
- CI-exact gates all exit 0: `check-conductor-permission-matrix.py` (48 API
  entries, 32 UI mutations — the restore inventory row added one UI entry and
  the gate still passes because the shipped control names the policy path and
  permission), `check-route-permissions.py` (41 declared, none new),
  `check-principal-identity.py` (4 tolerated, none new),
  `check-suite-inventory.py` (21 suites match; hive-conductor backend 3978
  collected = 3974 base + the note's +4 delta), `check-test-duplicates.py`.
- Live clean-setup evidence reproduced at this head: setup.spec.ts 8/8
  against a throwaway backend on :8102 (Vite on :8199; a scratch proxy config
  was needed because the shared :8101 dev port was occupied — removed after
  the run), plus a scratch fresh-session live spec driving the shipped
  Restore control through the real 403 -> elevation dialog ->
  `/v1/auth/elevate` -> PATCH retry -> restored selected tab. Both documented
  in the inventory note; the scratch spec itself is not committed (it depends
  on credentials from the setup run against the same data dir).
- Typed-client ratchet state at this head: `RATCHET_BASE_REV=origin/develop
  uv run python scripts/check-frontend-typed-client.py` -> FAIL with 165
  problems (112 NEW rows, 53 stale rows). Verified NOT caused by this round:
  the rows are this lane's earlier committed frontend work (`Elevation.tsx`,
  `Agents.tsx` etc. are new files vs `origin/develop` 7ba29c1c, where the
  gate passes). Unchanged resolution: the two-merge sequence — a grant/
  ledger adoption lands on develop first — which this lane is prohibited
  from performing. Recorded as an explicit integration blocker.
