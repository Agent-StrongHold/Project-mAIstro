---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# 1417 — Navigation coverage for the retained route inventory

`packages/hive-conductor/tests/e2e/navigation-coverage.spec.ts` adds ten
Playwright scenarios enforcing the route/entry-point inventory recorded in
`packages/hive-conductor/docs/route-inventory.md` (#1417): all 21 `fullNav`
destinations are reached from the desktop icon rail by keyboard activation
(three chunked specs), the same rows are reached from the narrow-screen drawer
with keyboard activation and asserted drawer dismissal (three chunked specs),
the `/optimization-inbox` alias resolves to the canonical `/optimizer` surface
and the `/cli/canvas` compatibility redirect resolves to `/design-studio`, each
leaving exactly one active rail entry carrying the destination's accessible
name, browser Back/Forward return canonical surfaces after rail navigation,
and the four intentionally URL-only legacy rows (`/work-items`, `/skills`,
`/memory`, `/evolution`) still render while the shell renders no nav link for
them.

Companion change: `AppShell.tsx` gains nav entries for the six retained
surfaces that had no entry point (`/schedules`, `/messages`, `/quotas`,
`/containers`, `/cli`, `/audit`), and `App.tsx` converts the
`/optimization-inbox` alias from a duplicate render into a redirect onto
`/optimizer`.

The count above does not move: `check-suite-inventory.py` collects this suite
with pytest, and pytest collects only its `test_*.py` files — `*.spec.ts`
files run in `ci.yml`'s `hive-conductor-e2e-ui` job instead (the `e2e-tests`
compose service runs every spec in the directory), so the Playwright addition
is invisible to the ledger by construction. The +0 block is recorded so the
change is legible in the ledger rather than silent.

Verified live against a locally built stack: `docker compose
-f docker-compose.test.yml up --build -d hive` (frontend rebuilt from this
worktree, so the served bundle carries the nav change), then the `e2e-tests`
service ran `navigation-coverage` 10/10, `design-studio-truthfulness` 7/7
(preserved `/cli/canvas` contract), and the full UI suite 131/131.
