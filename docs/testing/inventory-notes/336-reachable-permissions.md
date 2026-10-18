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
against the shipped `Setup.tsx` selectors; test count is unchanged (6), so no
inventory-delta entry is claimed for it. The suite now drives a real clean
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
  ("Live Operations"). Test count 6 unchanged; no inventory-delta claim.

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
