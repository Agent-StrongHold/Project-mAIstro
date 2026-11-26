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
