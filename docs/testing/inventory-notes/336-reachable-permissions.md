---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# Issue 336 — reachable UI permissions

The permission-policy tests add four node IDs covering policy-source wiring,
least-privilege daily setup, task-scoped elevation, and the admin break-glass
role. Frontend behavior is validated by the TypeScript build, the matrix
script, and the Playwright setup suite.

## Repair round (deep review)

Deep review of the implementation head found one contract violation, repaired
here: the first cut had removed the admin break-glass chat block from
`middleware/auth.py` and flipped three tests to assert the admin can chat.
The issue's bounded role contract says the admin "remains a separate
break-glass account and is deliberately blocked from chat", and no ADR
overrides that, so the block (`_ADMIN_CHAT_BLOCKED`, the 403, `_is_chat`) and
the original tests in `test_api.py`, `test_auth_middleware.py`, and
`test_chat_session_ownership.py` are restored. The generated API policy table
was verified byte-equivalent (content and order) to the pre-change
`_PROTECTED_OPS` via AST extraction, so the policy extraction introduced no
gate drift.

The shipped Playwright setup suite (`frontend/e2e/setup.spec.ts`) had gone
stale against the current five-step wizard (it predates the Accounts step, so
"next" never enabled and completion was unreachable). It was rewritten
against the shipped `Setup.tsx` selectors. The suite now drives a real clean
boot end to end: wizard → hardware → required account credentials → modules →
confirm → launch, which auto-logs in as the **daily user** and asserts the
chat surface is reachable for that account.

Residual gap, recorded honestly: the browser E2E covers clean setup and
daily-user chat reachability, not a per-role walk of all 31 `UI_MUTATIONS`
entries. Role-level coverage of those mutations is enforced at the API layer
by the backend suite and the CI matrix gate instead.

## Develop sync (merge resolution round)

The lane carried a preserved in-progress develop sync; both merges are now
resolved and committed (`6fc004fd7` = develop base `ab8b3737`, then
`5d14bb3ce` = `origin/develop` `c2a22e55`, clean). Resolution decisions:

- `middleware/auth.py`: the shared-policy generated table
  (`protected_ops_by_method()`) is kept over develop's inline dict, and
  `services/permission_policy.py` absorbed develop's three newer entries
  (GET `/v1/rum` -> `rum.read`, POST `/v1/chat/workflows` -> `dags.write`,
  POST `/v1/capabilities/approvals` -> `approvals.resolve`, the last ordered
  ahead of `/v1/capabilities`). The generated table was re-verified
  entry-for-entry (content and order) against develop's dict; develop's
  newer `Principal`-based middleware body and the `POST /v1/workspaces`
  ordinary-operation exemption are preserved.
- `routes/setup.py`: the daily account still receives
  `DAILY_USER_PERMISSIONS` from the shared policy source; develop's
  first-run question/rollback/flush-marker refactor merged around it.
- Frontend: `ElevationProvider` survives develop's App rewrite (develop had
  deleted the unrelated `ModeToggle`); `Elevation.tsx` now matches 403s via
  `ApiError.message` because develop's `ApiError` (#1436) carries the backend
  detail as the human-safe message instead of a `.detail` field. All
  `useAuthorizedAction` wrappings and admin-cause `disabled`/`title` gates
  are preserved; develop's optimistic schedule updates, tab/a11y refactors,
  and raw-fetch call sites (banked by the typed-client ratchet) are kept.
- `frontend/e2e/setup.spec.ts`: develop's evolved spec supersedes the repair
  round's rewrite — it covers the same five-step wizard plus the #287
  model-availability acknowledgement and the #443 crypto-identity/seed
  screens, and still ends asserting the daily-user auto-login landing
  ("Live Operations"). The merged spec has 8 tests (develop's #443 evolution
  added the two crypto-identity denials); Playwright specs are not part of the
  Python suite inventory, so no inventory-delta claim.

Post-merge evidence on `5d14bb3ce`:

- `uv run pytest packages/hive-conductor/backend/tests -q` -> 3630 passed,
  19 skipped.
- `npm run build` (tsc strict + vite) -> green after `npm install` picked up
  develop's fontsource dependencies.
- `scripts/check-conductor-permission-matrix.py` -> 47 API entries, 31 UI
  mutations.
- `scripts/check-route-permissions.py`, `scripts/check-principal-identity.py`,
  `scripts/check-suite-inventory.py` (after `uv sync --locked --extra dev`),
  and `scripts/check-vulture-baseline.py` with CI's exact arguments -> all
  green.

Known structural conflict, not fixable from this branch: develop's new
`scripts/check-frontend-typed-client.py` ratchet keys its ledger by line
number and reads authorizations from the merge base, so any change that
shifts a banked line in `frontend/src` (the elevation wrappings do, by
design) reports "NEW ... debt absent from the trusted base" even with a
candidate ledger regenerated to the current scan. Landing this branch needs
the two-merge sequence: the grant/ledger adoption must land on develop
first (CI-repair/exact-debt-ledger lane), then this branch merges clean.
Per campaign rules no ledger or grant rows were edited here.

## Validation evidence

On the repaired head, against a live throwaway instance and the worktree:

- `uv run pytest packages/hive-conductor/backend/tests -x -q` -> 2352 passed, 3 skipped (full backend package).
- `uv run python scripts/check-conductor-permission-matrix.py` -> "permission matrix OK: 44 API entries, 31 UI mutations".
- `uv run ruff check .` and `uv run ruff format --check .` -> passed.
- `npm run build` (frontend) -> tsc + vite build passed.
- `PLAYWRIGHT_BASE_URL=http://localhost:8199 npx playwright test e2e/setup.spec.ts` (backend booted on a fresh `CONDUCTOR_DATA_DIR`) -> 6 passed.
- `scripts/check-vulture-baseline.py`: no findings from `permission_policy.py` or the changed files; the only unclassified finding is a gitignored `node_modules/flatted/python/flatted.py` artifact absent from CI checkouts.

## Final validation round (head `a33476b99`, 2026-10-23)

All checks re-run at the final head; no code changed in this round — this
section records fresh evidence and corrects the stale test-count prose above.

- `uv run pytest packages/hive-conductor/backend/tests -q` -> **3630 passed,
  19 skipped**.
- `uv run python scripts/check-conductor-permission-matrix.py` -> "permission
  matrix OK: 47 API entries, 31 UI mutations"; gate wired at
  `.github/workflows/quality.yml:909` ("Conductor API/UI permission matrix").
- `uv run ruff check .` and `uv run ruff format --check .` -> pass.
- CI-exact gates, all exit 0: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (1322 -> 1322 reviewed
  identities, none new), `check-reachability.py`, `check-route-permissions.py`
  (41 declared, none new), `check-principal-identity.py` (4 tolerated, none
  new), `check-suite-inventory.py` (17 suites match).
- `npm run build` (tsc strict + vite) -> pass.
- **Playwright `e2e/setup.spec.ts` -> 8/8 passed against a live throwaway
  backend**: fresh `CONDUCTOR_DATA_DIR`, backend on :8102 (`uv run --no-sync
  uvicorn main:app`), vite dev on :8199 proxying `/v1` + `/health`, tests run
  inside the repo's `hive-playwright-373` image (@playwright/test 1.52 = its
  preinstalled browsers). The completing test walks first boot -> wizard ->
  Accounts -> Modules -> Confirm -> launch -> #443 recovery-seed
  acknowledgement -> "enter the hive" -> daily-user auto-login -> "Live
  Operations" reachable.
- Harness note for future lanes (cost a debugging cycle to learn): the
  backend's `session_cookie_secure` default is `True` and settings have **no
  `CONDUCTOR_` env prefix** — a plain-HTTP throwaway must boot with
  `SESSION_COOKIE_SECURE=false ALLOW_INSECURE_TRANSPORT=true` (the
  config-documented local-development escape). With the Secure cookie dropped
  by the browser, login returns 200 but whoami stays `authenticated:false` and
  the app shows the sign-in page — it looks like a product bug but is the
  harness misconfiguring the transport.
- Acceptance deltas visible at this head: role-scoped denials are enforced and
  tested at the API layer (permission+elevation boundary grid in
  `test_auth_middleware.py`, elevation success/refusal/scoped-grant/
  unassigned-rejection/task-completion-revocation in `test_api.py`, admin
  break-glass without chat, workspace non-member refusals in
  `test_workspace_mode.py` / `test_workspace_scoped_submission.py`); the
  per-role browser walk of all 31 UI mutations remains the recorded residual
  gap, intentionally covered by the API-layer suites plus the CI matrix gate.

## Develop-sync round (post-merge reconciliation, 2026-11-26)

Completing the preserved develop sync (7ba29c1cd0 + origin/develop 7926d9ab4d)
required reconciling the #336 inventory with develop's UI restructure (#2273
deleted the Agents/MCP/Skills pages; #2363 merged MessageBoard/OptimizationInbox
into Attention):

- `UI_MUTATIONS` drops the nine actions whose controls no longer ship
  (agent create/forge/edit/scan/delete, skill toggle, MCP add/test/remove);
  the daily role contract shrinks to the four permissions reachable UI still
  advertises (credentials.write, dags.write, schedules.write,
  workspaces.write). The API half keeps enforcing agents.*/skills.*/mcp.* for
  the break-glass admin, and gained develop's /v1/projects and
  /v1/eval-judge rows so `protected_ops_by_method()` provably equals the
  enforcement table in `services/authorization.py`.
- `check-conductor-permission-matrix.py` now also scans hand-written
  `lib/*.ts` mutation modules (attention.ts posts the proposal doors) while
  still excluding generated `src/api/` types, so removed actions cannot pass
  on generated strings.
- Attention's optimizer decision and HITL answer doors route through the
  canonical elevation affordance (`authorizedAction("dags.write", ...)`), and
  its catch blocks surface the verbatim denial/cancellation cause like
  WorkspaceTabs.
- New intercepted browser suite `e2e/workspace-attention-elevation.spec.ts`
  (+2): 403 on the proposal door must open the canonical elevation dialog,
  bind one password-backed task-scoped grant, and replay exactly the denied
  mutation; cancellation must refuse without replaying and stay retryable.
  Control-run: with the wiring temporarily reverted both cases fail (dialog
  never opens; request trace stalls at one 403); repaired, 6/6 pass in the
  permissions config alongside the archived-tab restore suite.

## Typed-client ratchet resolution (round of 2026-11-26, repair commit 55204762ae)

The "structural conflict" recorded above is resolved on-branch without any
grant. Reproducing CI exactly (`RATCHET_BASE_REV=origin/develop`) at head
`6c12914ce8` showed 108 problems whose ground truth was: 37 current keys
absent from the trusted base — 34 banked rows whose line keys the branch's
own edits had shifted plus 3 genuinely new rows in branch-new
`Elevation.tsx` (two hand-typed context shapes + the elevate fetch) —
reported twice each, plus the 34 now-stale ledger rows. Because `compare()`
keys rows by line, re-banking the shifted rows would itself be unauthorized
new debt; the only in-lane path the gate sanctions is eliminating the debt
and deleting the fixed rows (its docstring: "a fixed entry must be deleted
in the change that removes the debt").

So the violating rows moved out of `pages/`/`components/` into `src/lib/`
modules (the gate's sanctioned seam for shared HTTP and wire shapes, same
pattern as `lib/approvals.ts`): wire types per domain, RSI's resilient poll
client, Evolution's snapshot reads (per-section silent-skip preserved), and
the elevation call now through the shared client (refusal copy stays the
backend's verbatim detail; gains the client's timeout/RUM instrumentation).
38 rows were eliminated in total: the 37 keys above plus Evolution's
snapshot fetch that still sat at its unshifted trusted line inside the same
block. No test counts changed, so the inventory delta above is unchanged.

`quality/frontend-typed-client-baseline.json` went 122 -> 87 tolerated rows
(pure floor lowering; zero rows added; no grant touched). Gate result at the
tested commit: `ok: 16 raw fetch and 71 hand-typed declaration(s) tolerated,
none new`. Browser evidence re-established at the same content: permissions
suite 6/6 (intercepted) and `setup.spec.ts` 8/8 against a real clean-setup
backend on :8102 serving this production build.

## Independent verification round (head `ba3907e34f`, 2026-11-26)

Every material claim from the repair and sync rounds was re-executed first-hand
at the final head; no code changed in this round. Environment note: the
reference app's runtime deps (maistro-design/maistro-canvas) are not part of
the root dev env — `uv pip install -e packages/maistro-design` restores the
bootable state (the app hard-imports maistro_design; `uv sync --locked
--all-extras` alone does not).

- `RATCHET_BASE_REV=origin/develop uv run python scripts/check-frontend-typed-client.py` -> exit 0, "16 raw fetch and 71 hand-typed tolerated, none new" (the prior round's blocking finding, closed).
- `scripts/check-conductor-permission-matrix.py` -> OK: 51 API entries, 23 UI mutations (CI-exact, `quality.yml:1114`).
- `uv run ruff check .` / `uv run ruff format --check .` -> pass (3683 files).
- `scripts/check-suite-inventory.py` -> 21 suites match (37176 unique identities).
- Policy test set (permission_policy, setup_guard, auth_middleware, workspace_restore_policy, workspace_authority, home_routes, auth_routes) -> **155 passed**; `test_default_workspace.py` -> **18 passed** (default route + `workspaces.write` gate).
- Full backend package `uv run pytest packages/hive-conductor/backend/tests -x -q` -> **4544 passed, 112 skipped** (229.7s).
- Browser, permissions config (intercepted): **6/6** (restore elevation success/cancel/wrong-password-retry, membership denial surfacing, Attention optimizer+HITL doors).
- Browser, live clean setup: `setup.spec.ts` **8/8** against a throwaway backend on :8102 (fresh `CONDUCTOR_DATA_DIR`, `.venv` uvicorn, fresh `vite build`, no LLM gateway).
- Residual (unchanged, recorded, not regressed): the literal per-role live-browser walk of every advertised mutation (and the chat step, which needs a model gateway this environment lacks) remains covered at the API/policy layer by the 155+4544-test evidence; UI elevation task IDs are synthetic `ui-*` retired by TTL only.

## Independent verification round at the develop-merge head (`2ca17a341bcb`, 2026-11-27)

Starting head `2ca17a341bcb8f443f5c1ca4909d08261af9e9ad` (= `2245fe8222` +
merge of develop `73610a225d98`), working tree clean on arrival; nothing was
 salvaged because the prior round's diff-coverage repair was already committed.
Every check below was executed first-hand at this head; no code changed.

- Coverage gate diff leg, reproduced with CI's own arithmetic: full backend
  suite under `coverage run --branch --source=packages/hive-conductor/backend`
  (**4600 passed, 117 skipped** = the 4717 collected identities the inventory
  records) appended with the scripts producer over
  `tests/test_conductor...` (the new gate test, 4 passed), then
  `uv run python scripts/check-diff-coverage.py coverage.xml --base
  73610a225d98c602fc014dfbcfe3e399bbe79d9b` -> **exit 0** with the same scope
  line CI prints ("4 changed file(s) measured", 3 exempt test files; floors
  90% lines / 80% branch arcs met). This was the exact step that failed the
  merge-queue run at `b637299`. The 87% publish-set floor is untouched by
  this branch (the diff adds no code under the five publish-set roots), and
  the floor step itself passed at 93% in that same failing CI run.
- `scripts/check-conductor-permission-matrix.py` -> OK (**51 API entries,
  23 UI mutations**, exit 0); in-process proof `tests/test_check_conductor_permission_matrix.py`
  -> 4 passed; obligation digest registered in
  `tests/fixtures/ci_quality_obligations.json` and `tests/test_ci_quality_split.py`
  + `test_shipped_surface_truth.py` + `test_check_diff_coverage.py` ->
  159 passed.
- Focused policy tests (`test_permission_policy.py` + `test_setup_guard.py`)
  -> 28 passed; `ruff check .` + `ruff format --check .` -> clean;
  `scripts/check-suite-inventory.py` (full) -> 21 suites match, 37 652
  unique identities, 0 duplicate evidence;
  `RATCHET_BASE_REV=origin/develop scripts/check-frontend-typed-client.py`
  -> exit 0 ("16 raw fetch and 71 hand-typed tolerated, none new");
  `scripts/check-shipped-surface-truth.py` -> "matrix is complete".
- Full root suite `uv run pytest tests/ -q` -> **6490 passed, 140 skipped**
  (the merge added develop's tests; no regressions).
- Browser, permissions config (intercepted): **6/6** re-run first-hand at
  this head (restore elevation success/cancel/wrong-password retry,
  membership-denial surfacing, Attention optimizer door elevation+cancel).
- Acceptance spot-checks against the shipped tree: all 23 `UI_MUTATIONS`
  rows have a wired control through `useAuthorizedAction` (grep-verified per
  component); `POST /v1/workspaces` creation stays elevation-exempt while
  `POST /v1/workspaces/default` keeps the `workspaces.write` gate per
  ADR-092326-7ed7 AC-6 (covered by the full backend run, which includes
  `test_default_workspace.py` and the elevation expiry/revocation tests in
  `test_auth_routes.py`); `AccountBanner` names the admin-gated surfaces
  with cause; `/agents` `/skills` `/mcp` deep links redirect to
  `/capabilities` without reviving controls; no closure keywords in any lane
  commit and the PR body says only "Refs #336".
- `frontend/e2e/setup.spec.ts`, `Setup.tsx`, and `SetupChecklist.tsx` are
  byte-unchanged since `ba3907e34f`, where the live clean-setup run recorded
  8/8; that browser evidence carries to this head for the frontend, and the
  backend half of the same path (setup -> daily login -> whoami ->
  `permissions == DAILY_USER_PERMISSIONS` -> workspace create -> 403 ->
  elevate -> archive/restore -> member matrix -> admin chat block) is
  re-proven first-hand at this head inside the 4600-test backend run.
- Residuals (unchanged, recorded, not regressed): the per-role live-browser
  walk of every advertised mutation and an in-browser chat step remain
  covered at the API/policy layer instead (this issue's E2E criterion is
  therefore only partially proven in-browser); UI elevation task IDs are
  synthetic `ui-*` retired by TTL only; `frontend/e2e/` suites still have no
  CI owner (standalone configs; compose e2e runs `tests/e2e/`, which does
  exercise the shipped `WorkspaceTabs` skeleton + a11y with the
  `ElevationProvider` wired via the updated `Dockerfile.playwright`).
  Hosted CI at `2ca17a341bcb` had not reported at recording time.

## Develop sync round 3 + coverage-gate repair (merge `13988fdc70`, 2026-11-27)

Merge of `origin/develop` `618954f05` (M2-A1 Warden/Sentinel #2527, keyboard
reachability #2530, Sentinel signing #2533) resolved the preserved in-progress
sync; two textual conflicts, both semantic combinations:

- `DagBuilder.tsx` `handleSaveDag`: develop's serialized+coalesced save loop
  (#370 save race) is kept, and each PUT inside the loop is wrapped in
  `authorizedAction("dags.write", ...)` so a 403 still routes through the
  elevation dialog and retries — the coalescing loop and the elevation gate
  compose without either semantics being lost.
- `Settings.tsx` settings value display: develop's non-interactive div is
  taken (the pointer-only click-to-edit violated the #2530 keyboard gate —
  `check-keyboard-controls.mjs` rejects click-only generic controls). The
  permission-gated "edit" button with its cause title ("Config write
  permission required — elevation or an admin role is required...") remains
  the only mutation path, satisfying #336's elevate-or-hide-with-cause rule;
  the dead `canEditSystemSettings` click gate (whose only effect was the
  removed click handler) and the now-unused `useUser` import are deleted.
- Ledgers: `vulture-baseline.json` takes develop's removal of the
  `types/security.py::repair_action` row (develop's own fix removed the dead
  variable); `frontend-typed-client-baseline.json` and
  `shipped-surface-truth.json` keep the branch's debt-eliminated versions
  (typed-client gate re-run: none new).

Named CI failure at `b637299889` (merge-queue evaluation, run 45914333217:
"Coverage gate (publish-set floor + diff coverage)") diagnosed: the branch
was based on an older develop, and the merge-queue's auto-merge combined both
sides' edits to `services/engine.py` (39 lines),
`services/agent_materialization.py`, and the harness/materialization tests
into a broken tree — seven `RuntimeError: Event loop is closed` failures in
the gate job's serial hive-conductor backend producer. Repair = this explicit
merge (develop's backend restored wholesale, the branch's permission work on
top), proven by running every gate leg locally at `13988fdc70` with CI's
exact commands:

- Serial producers (gate job combine step, all pass, zero loop errors):
  hive-conductor backend **4609 passed, 117 skipped** (5m16s, under
  coverage); maistro-server 746+18 skipped; maistro-turing 233 + backend 138;
  maistro-design 724+1 skipped; maistro-registry 366 (with the named root
  files); maistro-ext-harness 273; maistro-ext-sdk 147; root scripts producer
  **6512 passed, 140 skipped** (17m).
- `coverage-postgres` producer against a fresh local `pgvector/pgvector:pg17`
  (CI env incl. `MAISTRO_REQUIRE_PG_LEGS=1`): tests/migrations 173 passed;
  `alembic upgrade head` (chain incl. develop's `071_sentinel_decision_integrity`)
  then the schema-suite list **7693 passed, 98 skipped, 4 xfailed**; backlog
  115; canvas 666; hive-conductor evolve legs 58; brief_commit 49.
- `coverage-unit` producer: core **17948 passed, 1303 skipped**, canvas 610,
  evolve 1211, rsi 1863, bootstrap 274.
- `coverage-archive` producer not runnable locally (MinIO unbuildable: no Go
  toolchain, Hub pull denied — the reason CI builds from source); its absence
  makes the local floor stricter, archive files are not in this diff, and the
  floor leg already passed at 93% inside CI's own failing run.
- Gate combine in CI's order: floor `coverage report --fail-under=87` over the
  publish-set data -> **93%, exit 0**; after appending postgres + serial
  producer data, `coverage xml` + `check-diff-coverage.py coverage.xml --base
  618954f05` -> **exit 0**, "4 changed file(s) measured" (`middleware/auth.py`,
  `routes/setup.py`, `services/permission_policy.py` above 90% lines / 80%
  branches; the three changed test files exempt as evidence).
- Deterministic gates at this head: ruff check + format clean; suite
  inventory **21 suites match (37,751 identities)** incl. develop's two new
  Playwright specs; permission matrix **51 API / 23 UI**; typed-client none
  new; vulture with CI's exact arguments **1217 = 1217** (base `618954f05`);
  frontend eslint 0 errors / 49 warnings (max 96); `tsc` app + node configs
  clean; `check-keyboard-controls.mjs` pass.

Residuals unchanged from the previous round (per-role live-browser walk,
synthetic `ui-*` elevation task IDs, `frontend/e2e` CI ownership). Hosted CI
has not reported at this head; the gate evidence above is local.

## Independent verification round (head `4d22748717`, 2026-11-28)

Third develop sync completed: `origin/develop` tip `547eb70afd64` merged into
`auto-336` as `4d22748717` (ort strategy, auto-resolved with no conflict
markers; `git merge-base HEAD origin/develop` == `547eb70afd64` exactly, tree
clean). `git diff --numstat origin/develop -- quality/` shows only the
intentional `frontend-typed-client-baseline.json` (+2/−37 debt elimination)
and `shipped-surface-truth.json` (7/7) deltas — no ledger row loss from the
merge. The merge touched no frontend files and none of `routes/setup.py`,
`middleware/auth.py`, or `services/permission_policy.py`, so the permission
surface is byte-identical to the previously verified heads; develop's new
backend services (entra_jit, user_model, oauth_login, brief_chat) are
orthogonal and covered by the suite below. `setup.spec.ts`, `Setup.tsx`, and
`routes/setup.py` remain byte-identical to `10bfbe38`, so the live clean-setup
8/8 proof carries over.

Fresh evidence at this head (all executed locally, CI-exact arguments where
applicable):

- `uv run coverage run --branch --source=packages/hive-conductor/backend -m
  pytest packages/hive-conductor/backend/tests --timeout=30 -q` -> **4666
  passed, 120 skipped** (4786 total; +54 from the sync; suite-inventory gate
  records 4786 and matches).
- `uv run coverage run --append --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py
  --timeout=30 -q` -> **6593 passed, 141 skipped**; targeted re-run of
  `tests/test_check_conductor_permission_matrix.py` +
  `tests/test_ci_quality_split.py` -> **100 passed**.
- `uv run coverage xml -o coverage.xml` then `uv run python
  scripts/check-diff-coverage.py coverage.xml --base 547eb70afd64` (CI's
  `DIFF_BASE_SHA` = PR base = develop tip) -> **exit 0**, 4 changed files
  measured, 3 test-file exemptions, "ok: every measured file this change
  touches is at or above 90% lines / 80% branch arcs".
- `uv run python scripts/check-conductor-permission-matrix.py` -> **exit 0**,
  "permission matrix OK: 51 API entries, 23 UI mutations"; `UI_MUTATIONS` is
  23 entries in code and `DAILY_USER_PERMISSIONS` stays derived from it
  (`credentials.write`, `dags.write`, `schedules.write`, `workspaces.write`).
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-frontend-typed-client.py` -> **exit 0**, base auto-resolves
  to `547eb70afd64`: 26/96 banked -> 16 raw fetch / 71 hand-typed tolerated,
  none new.
- `uv run python scripts/check-shipped-surface-truth.py` -> **exit 0**
  ("complete").
- `uv run ruff check .` and `uv run ruff format --check .` -> **clean**.
- `npx playwright test --config playwright.permissions.config.ts` -> **6/6
  passed** (elevation success, cancel-refusal without replay, daily-owner
  elevate+restore, wrong-password explicit cause with retry, membership
  denial not hidden by elevation).
- Closure-keyword review: no `fixes/closes/resolves` in the PR body
  ("Refs #336" only) or any `origin/develop..HEAD` commit message.

Residuals unchanged (per-role live-browser walk of all 23 UI mutations —
API-layer covered by the backend suite and the matrix gate; synthetic `ui-*`
elevation task IDs; `frontend/e2e` CI ownership). Hosted CI has not reported
at this head; the evidence above is local.
