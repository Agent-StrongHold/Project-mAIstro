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

## Validation evidence

On the repaired head, against a live throwaway instance and the worktree:

- `uv run pytest packages/hive-conductor/backend/tests -x -q` -> 2352 passed, 3 skipped (full backend package).
- `uv run python scripts/check-conductor-permission-matrix.py` -> "permission matrix OK: 44 API entries, 31 UI mutations".
- `uv run ruff check .` and `uv run ruff format --check .` -> passed.
- `npm run build` (frontend) -> tsc + vite build passed.
- `PLAYWRIGHT_BASE_URL=http://localhost:8199 npx playwright test e2e/setup.spec.ts` (backend booted on a fresh `CONDUCTOR_DATA_DIR`) -> 6 passed.
- `scripts/check-vulture-baseline.py`: no findings from `permission_policy.py` or the changed files; the only unclassified finding is a gitignored `node_modules/flatted/python/flatted.py` artifact absent from CI checkouts.
