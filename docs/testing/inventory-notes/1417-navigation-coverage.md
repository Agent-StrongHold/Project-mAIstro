---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# 1417 — Navigation coverage for the retained route inventory

`packages/hive-conductor/tests/e2e/navigation-coverage.spec.ts` adds thirteen
Playwright scenarios enforcing the route/entry-point inventory recorded in
`packages/hive-conductor/docs/route-inventory.md` (#1417): every `fullNav`
destination is reached from the desktop icon rail by keyboard activation and
from the narrow-screen drawer with keyboard activation and asserted drawer
dismissal, each landing leaving exactly one active rail entry carrying the
destination's accessible name; the `/optimization-inbox` alias resolves to the
canonical `/optimizer` surface and the `/cli/canvas` compatibility redirect to
`/design-studio`; browser Back/Forward return canonical surfaces; and the four
intentionally URL-only legacy rows (`/work-items`, `/skills`, `/memory`,
`/evolution`) still render while the shell renders no nav link for them.

Coverage is per principal, matching the permission contract (route-inventory
§ Permission contract check): the setup wizard's daily user is provisioned
with only `dags.write` (`backend/routes/setup.py`
`_DEFAULT_DAILY_USER_PERMISSIONS`), so the ordinary-principal walks cover the
nineteen unscoped rows and additionally assert that the two entries carrying
a mutation scope — Schedules (`schedules.write`) and Containers
(`containers.control`, `AppShell.tsx` `visibleNav`) — are absent from BOTH
chrome modes for that account. The admin account (which
`principal_has_permission` passes through every gate) walks the two
grant-gated rows from both chrome modes. That split is the review-driven
repair for the previously unconditional entries: without it the default user
landed on screens whose every mutation 403s.

Companion change: `AppShell.tsx` gains nav entries for the six retained
surfaces that had no entry point (`/schedules`, `/messages`, `/quotas`,
`/containers`, `/cli`, `/audit`) — two of them scope-conditional as above —
and `App.tsx` converts the `/optimization-inbox` alias from a duplicate
render into a redirect onto `/optimizer`.

The count above does not move: `check-suite-inventory.py` collects this suite
with pytest, and pytest collects only its `test_*.py` files — `*.spec.ts`
files run in `ci.yml`'s `hive-conductor-e2e-ui` job instead (the `e2e-tests`
compose service runs every spec in the directory), so the Playwright addition
is invisible to the ledger by construction. The +0 block is recorded so the
change is legible in the ledger rather than silent.

Verified live in this worktree against a locally built stack (backend run
from `packages/hive-conductor/backend` per the test compose env:
`SESSION_COOKIE_SECURE=false ALLOW_INSECURE_TRANSPORT=true`, fresh
`CONDUCTOR_DATA_DIR`, serving `frontend/dist` rebuilt from this tree):

- `navigation-coverage` 13/13 passed (the run above).
- `design-studio-truthfulness` passed within the full-suite run (preserved
  `/cli/canvas` contract).
- Full UI suite minus four container-harness-bound specs: 112 passed with the
  only failure `pm-workflow` 15c, and pm-workflow minus 15c passes 16/16.

Environmental exclusions, each reproduced identically against a control
checkout of `origin/develop` (b78637f52b) in the same ad-hoc harness, so none
is a regression of this branch:

- `widget-capabilities`, `dashboard-metrics-states`, `deck-sanitization`
  build ephemeral harness pages from `/tests/frontend/...` absolute paths and
  a `/tests/node_modules` resolution root that only exist inside ci.yml's
  pinned `tests/Dockerfile.playwright` image.
- `pm-workflow` 15c matches the console text "Refused to load the script",
  the CSP violation wording of the image's pinned `@playwright/test@1.52.0`
  Chromium; a current Chromium words it "Loading the script ... violates". A
  probe against the same stack confirms the policy is enforced (violation
  reported, script blocked), and the spec's 15/15b siblings pass.
