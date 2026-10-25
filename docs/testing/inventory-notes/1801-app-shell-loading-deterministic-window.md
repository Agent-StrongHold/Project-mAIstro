# Issue #1801 — app-shell-loading e2e: make the loading window a fact, not a hope

No counts moved: same spec, same four tests, no additions or removals. The
`inventory-delta:` front-matter block is therefore absent by the convention in
this directory's README (an absent block records zero movement, which is what
happened). `scripts/check-suite-inventory.py` passes at head with
`packages/hive-conductor/tests/e2e: 23` unchanged.

## What changed

`packages/hive-conductor/tests/e2e/app-shell-loading.spec.ts`, third test only
("the shell chrome appears before the auth chain finishes for a signed-in
user"). The test asserted a transient loading state whose visibility depended
on a fixed 400 ms sleep inside the `whoami` route handler — likely rather than
certain, and only observable at all when the navigation's `whoami` actually
reaches the network layer (`loginAsAdmin` fires two more `whoami` calls of its
own via `App.tsx` `handleAuthenticated` and `Login.tsx` `completeAuth`, and
their responses sit in the browser's HTTP cache under the exact URL the tested
navigation fetches). The fix, per the issue's stated preference:

1. **Settle the login page first** (shell's Chat link visible), so the
   login flow's trailing `whoami` calls are done writing cache entries and
   cannot be mistaken for the navigation's request.
2. **Purge the HTTP cache** (`Network.clearBrowserCache` over CDP; the e2e
   project is chromium-only) so the navigation's `whoami` must go out over
   the network and can be intercepted.
3. **Hold the intercepted response open on a promise** the test resolves
   after the skeleton assertions, replacing the fixed sleep — while held,
   `AuthGuard`'s `ready` cannot flip and the skeleton cannot unmount under
   the assertions.
4. **Bound the wait for the interception itself**, so a `whoami` that never
   reaches the route fails immediately with a message naming that cause,
   instead of a bare 5 s `waitForSelector` timeout that looks like a shell
   that never finished loading.

## Validation evidence (first-party, at this head)

- `npx tsc --noEmit --strict` over the spec and `session.ts`: clean.
- `npx playwright test --list`: 4 tests in the spec, 121 in the suite —
  matching the CI counts quoted in the issue.
- Live full-stack run in CI's own image
  (`mcr.microsoft.com/playwright:v1.52.0-noble`, `@playwright/test@1.52.0`)
  against the compose `hive` service: `app-shell-loading --repeat-each=6
  --retries=0` → **24 passed**, including 6 runs of the fixed test.
- Diagnostic-path proof: a mutated copy whose route handler never marks the
  interception fails at the bound with exactly
  `no /v1/auth/whoami request was intercepted during the navigation…`
  (the named failure, not a selector timeout).
- Root-cause honesty: a standalone probe in the same browser image could **not**
  reproduce the cached-`whoami` bypass on a warm local box — the second
  navigation's `whoami` reached the route every time. The flake is
  intermittent and CI-only; the fix therefore does not lean on the cache
  theory being the whole story: the hold makes the window deterministic
  whenever interception happens, the purge removes the cached-response path
  if that is what CI hits, and the bounded wait turns any residual
  non-interception into a diagnosis instead of a mystery.
