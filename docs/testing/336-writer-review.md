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

## Develop-sync round (2026-11-26, implement/verify worker)

The worktree carried an unfinished merge of stale develop tip 7ba29c1cd0 (an
ancestor of origin/develop 7926d9ab4d) with nine conflicted paths. It was
completed, then origin/develop was merged on top (conflict-free delta).
Resolution policy per file:

- `middleware/auth.py`: develop's single enforcement table lives in
  `services/authorization.py`; the `_PROTECTED_OPS` alias points at it and
  `_required_permission` delegates to `authorization.required_permission`.
- `services/permission_policy.py`: added develop's newer rows (DELETE+POST
  /v1/projects -> projects.write, POST /v1/eval-judge -> eval.score) so the
  #336-generated table equals the enforcement table byte-for-byte in content;
  dropped the nine UI_MUTATIONS rows whose controls develop deleted
  (Agents/MCP/Skills pages, #2273; optimizer inbox folded into Attention,
  #2363). DAILY_USER_PERMISSIONS is derived, so the provisioned daily role
  is now exactly the four reachable surfaces (credentials.write, dags.write,
  schedules.write, workspaces.write) — least privilege against the reachable
  inventory, admin break-glass unchanged and still chat-blocked.
- Frontend conflicts (App.tsx, Credentials.tsx, Settings.tsx,
  LlmProviders.tsx): kept both the #336 elevation affordances and develop's
  AuthorizationContext model; explicit denial causes retained (Settings edit
  button now gates on the same config.write predicate the save path enforces
  and names both denial causes; LlmProviders cause line follows the
  permission model rather than a hardcoded admin check).
- Modify/delete pages (Agents/MCP/OptimizationInbox/Skills .tsx): accepted
  develop's deletions; unrouted in the merged App.tsx (deep links redirect to
  /capabilities), content recoverable at the prior head.
- `Attention.tsx` repair: the merged optimizer decision + HITL answer doors
  (both dags.write protected ops) posted raw with no elevation path — wired
  through `authorizedAction`, with verbatim cause surfacing in the catch.

Evidence at the final head of this round:

- `uv run python scripts/check-conductor-permission-matrix.py` -> OK (51 API
  entries, 23 UI mutations; one policy source, CI-exact invocation).
- `uv run python scripts/check_enumerations.py` -> no new gaps;
  `scripts/check-route-permissions.py` -> 42 declared, 0 undeclared.
- `uv run pytest packages/hive-conductor/backend/tests/test_permission_policy.py
  test_setup_guard.py test_registration_policy.py test_ui_auto_climb_defaults.py
  test_workspace_restore_policy.py test_workspace_authority.py
  test_home_routes.py -q` -> 145 passed (includes the live clean-setup
  restore matrix: owner/editor/viewer/nonmember, admin 404 + chat 403 +
  invite flow, elevation success/refusal/retry).
- `tsc -p tsconfig.json --noEmit` -> clean; root `uv run ruff check .` and
  `uv run ruff format --check .` -> clean (3679 files).
- Playwright permissions config: 6/6 (4 archived-tab restore + 2 new
  Attention elevation cases); control run with the wiring reverted -> 2/2
  new cases fail as named, then restored.
- `scripts/check-suite-inventory.py` -> 21 suites match (backend pytest node
  counts unchanged; the +2 e2e cases are playwright, documented in the
  inventory note).
- Residual (unchanged class, not from this round): `RATCHET_BASE_REV=origin/
  develop scripts/check-frontend-typed-client.py` exits 1 with 108 problems,
  all in pre-existing lane frontend files (Elevation, PersonaWizard,
  WorkspaceTabs, WorkspaceToolBindings, Containers, DagBuilder, Evolution,
  RSI) — no row names a file edited this round. The two-merge grant sequence
  recorded previously remains the integration-stage resolution; this lane
  cannot land grants.

## Typed-client CI-repair + final-head evidence round (2026-11-26)

Start: head `6c12914ce8` with one preserved external modification
(`playwright.permissions.config.ts` gained a comment-only `devskim: ignore
DS162092` line at 14:07 during the prior verification — salvaged, committed
verbatim in the repair commit below).

Blocking finding resolved. The prior round's #1 finding (typed-client
ratchet exits 1 with 108 problems) was reproduced and root-caused: CI-exact
run at `6c12914ce8` -> 108 failures = 37 current keys absent from the
trusted base (34 banked rows whose line keys this branch's own edits
shifted + 3 genuinely new rows in branch-new `Elevation.tsx`) reported in
two failure classes each, plus 34 stale ledger rows. `compare()` keys rows
by exact file:line, so re-banking shifted rows is itself unauthorized new
debt — the documented two-merge grant path is not reachable from this lane.
The gate's own sanctioned alternative was taken instead: eliminate the debt.
All violating wire shapes and fetch call sites moved from `pages/` and
`components/` into `src/lib/` modules (the seam the gate names for shared
HTTP: lib/elevation.ts, lib/rsi.ts, lib/evolution.ts, lib/dagTypes.ts,
lib/containers.ts, lib/workspacePersonas.ts, lib/personaWizard.ts), pages
import from there, and `quality/frontend-typed-client-baseline.json` had
its 38 fixed rows deleted (122 -> 87; zero rows added — a pure floor
lowering, no grant involved, exactly the ledger operation the gate's
docstring prescribes for removed debt).

Evidence, all executed at the working-tree content of the repair commit
`55204762ae` (parent `6c12914ce8`):

- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-frontend-
  typed-client.py` -> **exit 0**, "ok: 16 raw fetch and 71 hand-typed
  declaration(s) tolerated, none new" (was 108 problems).
- `npx tsc -p tsconfig.json --noEmit` and `tsc -p tsconfig.node.json --
  noEmit` -> clean; `npx vite build` -> green (production bundle, then
  served by the throwaway backend below); `npm run lint` -> 0 errors (49
  warnings, ceiling 96).
- Browser, permissions config (intercepted): 6/6 — archived-tab restore
  elevation success/refusal/cancel/retry, membership-denial surfacing, and
  the two Attention optimizer/HITL elevation doors. This directly re-proves
  the elevation affordance after its fetch moved to the shared client: the
  wrong-password refusal still shows the backend's verbatim "Invalid
  password" and stays retryable.
- Browser, live clean setup: `e2e/setup.spec.ts` **8/8** against a real
  throwaway backend (`uvicorn main:app` on 127.0.0.1:8102, fresh
  CONDUCTOR_DATA_DIR, no gateway — the wizard's unverified-models
  acknowledgement path) serving this production build. Completing-setup
  provisions the real admin + daily accounts and lands the daily user on
  Home. This closes the prior round's "setup 8/8 only at an earlier head"
  gap; the per-role API matrix (owner/editor/viewer/nonmember + admin
  break-glass) remains covered by the backend tests below.
- `uv run pytest packages/hive-conductor/backend/tests/test_permission_
  policy.py test_setup_guard.py test_auth_middleware.py test_workspace_
  restore_policy.py test_workspace_authority.py test_home_routes.py -q` ->
  **145 passed** (policy source wiring, least-privilege daily provisioning,
  elevation success/refusal/retry, per-role restore matrix, admin 404 +
  chat 403 + invite flow). Backend files are untouched by this round, so
  the prior full-package run (4544 passed, 112 skipped at `6c12914ce8`)
  stands for the rest of the package.
- `uv run ruff check .` + `uv run ruff format --check .` -> clean (3683
  files). `scripts/check-conductor-permission-matrix.py` -> OK 51 API / 23
  UI; `check-route-permissions.py` -> 42 declared, 0 undeclared;
  `check-principal-identity.py` -> 0 violations; `check_enumerations.py` ->
  no new gaps; `check-suite-inventory.py --suite packages/hive-conductor/
  backend/tests` -> match (no test added or removed this round, so the
  recorded deltas are unchanged); `check-test-duplicates.py` -> ok.

Known limitation retained (documented, not regressed): UI-initiated
elevations mint synthetic `ui-*` task IDs that the backend never sees
completed/revoked; only TTL expiry retires them (covered by
`test_auth_routes.py`'s 15-minute default/override tests). A full
elevation-lifecycle repair stays open for the integration stage.

No closure keywords were added anywhere; the PR/issue state is untouched.

## Repair round at `2941907adb` (2026-11-26)

The merge-queue evaluation at this head failed five CI gates. Each defect was
reproduced locally before repair; none was addressed by scanner guesswork.

- `exact-debt-ledger` / vulture per-identity ledger: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` -> **passes at this head** (1219 reviewed
  identities -> 1219 findings, unclassified 0, never_allowlist 0). The
  failing step in that workflow is `check-shipped-surface-truth.py` (it runs
  in the same job, `vulture-ratchet.yml`), not the vulture comparison
  itself. `quality/vulture-baseline.json` was therefore **not** amended —
  there is no unbanked identity to bank and no fixed identity to retire.
- Shipped-surface truth: the typed-client repair (`55204762ae`) moved the
  Evolution/RSI mutating calls from `pages/` into `lib/evolution.ts` /
  `lib/rsi.ts`, leaving five stale matrix rows (pages) and five unclassified
  surfaces (lib). The five rows in `quality/shipped-surface-truth.json` were
  re-pointed to the lib sources (the two RSI rows also picked up the
  renamed interpolations `${runId}`); dispositions, reasons and effect
  owners are unchanged. `check-shipped-surface-truth.py` -> complete;
  `tests/test_shipped_surface_truth.py` -> 2 passed.
- Credential field labels: the new elevation dialog rendered a raw
  `type="password"` input. Replaced with the shared `SecretField` (label
  "Account password", show/hide control, `autoComplete="current-password"`,
  Enter-to-submit preserved). `check-secret-field-labels.py` -> OK;
  `tests/test_check_secret_field_labels.py` -> 2 passed.
- Quality-split profile: `quality-enumerations` gained the
  `check-conductor-permission-matrix.py` step without recording its digest
  in `tests/fixtures/ci_quality_obligations.json`. Added the step's sha256
  (`ca0a407d…`) to the fixture. `tests/test_ci_quality_split.py` -> passed
  (9/9 incl. parametrized).
- `hive-conductor-e2e-ui` (reproduced with the exact CI compose command,
  plus a local-only ports override because an orphan proxy from a previous
  session holds host 127.0.0.1:8101; the Playwright suite addresses the
  compose-network hostname, so the outcome is unaffected): first run
  208 passed / 4 failed / 20 skipped, exactly matching CI. Four root
  causes, all fixed:
  1. `tests/Dockerfile.playwright` copies a frontend whitelist into the
     test image; `WorkspaceTabs.tsx` now imports `./Elevation`, so the
     skeleton spec's esbuild bundle died with `Could not resolve
     "./Elevation"`. Added `Elevation.tsx` + `lib/elevation.ts` to the
     whitelist (their own imports — `lib/api`, `shared` — are already
     copied).
  2. The skeleton harness mounted `WorkspaceTabs` without
     `ElevationProvider`; `useAuthorizedAction` throws outside the
     provider, so the component crashed before rendering the skeleton.
     The harness entry now wraps in `ElevationProvider`, mirroring the
     shipped `App` composition.
  3. `DagBuilder.handleRun` forced `requestElevation("dags.write")` for
     every non-admin. The setup-provisioned daily user legitimately holds
     `dags.write` (policy inventory), so this stranded exactly the
     ordinary workflow #336 unblocks and blocked the PM-driven DAG specs.
     The gate is removed; the run socket is still enforced server-side
     (`routes/ws.py` authenticates the upgrade with
     `permission="dags.write"`), which the page surfaces verbatim.
  4. `workspace-a11y`'s invite-refusal case relied on the daily user being
     refused `workspaces.write` by the permission table — a premise #336
     deliberately removed (and `set_member` never validates user
     existence, so the invite now succeeds). The refusal is now stubbed at
     the network layer with the route's own 403 copy ("only an owner can
     add workspace members"), keeping the a11y contract under test (the
     panel's error region is an alert) independent of the permission
     matrix. The message intentionally does not name `workspaces.write`,
     so the elevation affordance stays closed.
  After the fixes: **232 passed, 0 failed** (~3.5m).
- The lane's own permission specs (`frontend/e2e`, standalone
  `playwright.permissions.config.ts`) initially failed on the SecretField
  change: `dialog.getByLabel("Account password")` strict-matches both the
  labeled textbox and the "Show Account password" reveal button. The two
  helpers now use `getByRole("textbox", { name: "Account password" })`.
  Suite result: **6 passed** (elevation success, wrong-password refusal,
  cancel-without-replay, retry, denial scoping) — the issue's
  approval/elevation success/refusal/retry evidence.
- Frontend `tsc --noEmit` -> clean; the compose build compiles the SPA
  with these changes (the hive image built successfully three times).
- Full re-validation at the repaired tree: `uv run pytest
  packages/hive-conductor/backend/tests -q` -> **4544 passed, 112
  skipped** (= recorded inventory 4656); `uv run pytest tests/ -q` ->
  **6429 passed, 140 skipped**; `uv run ruff check .` +
  `ruff format --check .` -> clean; `check-conductor-permission-matrix.py`
  -> OK (51 API / 23 UI); `check-ratchet-provenance.py`,
  `check-frontend-typed-client.py`, and the other `lint-and-type-check`
  static steps all exit 0; `check-suite-inventory.py` -> 21 suites match
  the recorded inventory (no pytest-collected test added or removed, so no
  inventory delta is owed).

No ledger/grant file was edited in this round; no closure keywords added;
no remote mutation performed.
