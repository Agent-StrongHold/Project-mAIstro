---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# Issue 336 — archived Workspace restore elevation

Adds four route-intercepted Playwright cases (not counted by the Python suite
inventory) against the shipped app and archived-tab restore control:

- daily owner requests only `workspaces.write`, confirms their own password,
  retries the PATCH once, and selects the restored tab;
- cancellation sends no elevation request or mutation retry and remains retryable;
- wrong password is explicit and allows retry without replaying the mutation;
- a post-elevation membership denial remains visible and never loops elevation.

The daily-owner case was run before the production change and failed because
Restore never opened the elevation dialog. After the change all four cases pass;
the strict TypeScript/Vite build also passes.

Four additional parametrized backend cases drive the actual clean setup, daily
login, Workspace creation, own-password elevation, archive and restore APIs.
The daily account receives only the shipped setup permissions. The separate
admin is first refused as a nonmember and remains blocked from chat; an explicit
owner invitation lets it change the daily caller's membership. Restore then
succeeds only for an owner, refuses editor/viewer with 403 and nonmember with
404, without changing archived state on denial.

The browser tests prove control wiring, not full clean-setup browser E2E.
The broader per-role, per-action acceptance matrix and elevation lifetime are
still incomplete; see `docs/testing/336-writer-review.md`.

Run with `npx playwright test --config=playwright.permissions.config.ts` from
`packages/hive-conductor/frontend`. The runner owns an isolated loopback Vite
server; all API responses are intercepted.

## Live clean-setup composition (validation round at head `auto-336`, 2026-11-26)

The intercepted wiring proof was additionally composed against a real backend:
a fresh `CONDUCTOR_DATA_DIR`, throwaway backend on :8102
(`SESSION_COOKIE_SECURE=false ALLOW_INSECURE_TRANSPORT=true`, the documented
local-transport escape), Vite on :8199 proxying to it. Against that instance:

- shipped `e2e/setup.spec.ts` -> **8/8 passed** (first boot -> wizard ->
  Accounts -> Modules -> Confirm -> launch -> daily-user auto-login ->
  "Live Operations");
- a scratch live spec (not committed — it depends on credentials provisioned
  by that setup run against the same data dir) logged the provisioned daily
  user into a **fresh browser session with no elevation**, archived its
  Workspace through the shipped APIs from a separate elevated session, clicked
  the shipped Restore control, and verified the canonical elevation dialog
  opens against the real 403, completes via the real `/v1/auth/elevate` with
  the daily account's own password, retries the real PATCH, and lands the
  restored Workspace as the selected live tab. This directly demonstrates the
  issue's deadlock-free owner path end to end. Elevation is session-scoped at
  this head, which is why the provisioning calls ran in a separate session:
  the defect scenario is a fresh session, and that is what the test drives.

Note for future live rounds: Vite's dev proxy targets `localhost:8101`; when
that port is occupied by a foreign dev server, a scratch vite config pointing
at the throwaway port is needed (removed after the run here).
