# Issue #2361 — Capabilities RUM route root + capabilities-shell admin login

Repair round for the #2273 delete slice (#2361). Two e2e-facing fixes, no new
test cases: one assertion added to an existing test, one spec-internal login
sequence fix, and one production-schema line.

## What moved and why

No suite count moved: `rum-telemetry.spec.ts` gains one assertion inside the
existing "page route templates are the single SPA segment" test, and
`workspace-capabilities-shell.spec.ts` changes only the login sequence inside
its existing happy-path test. `scripts/check-suite-inventory.py` was run
before and after the edits and reports all 21 suites matching the recorded
inventory, so no `inventory-delta:` block is written — per
`inventory-notes/README.md`, a note without front matter is the correct form
for a change that moved no count.

## The fixes

1. `frontend/src/lib/rumSchema.ts` — the #2273 slice registered
   `<Route path="capabilities">` in `App.tsx` and retargeted
   `rum-telemetry.spec.ts`'s page-load test at `/capabilities`, but never
   added `capabilities` to `PAGE_ROUTE_ROOTS`. Every web_vital event on the
   new primary surface therefore normalized to `"unknown"`, failing the
   page-load test's `/^\//` route assertions deterministically. Proven by
   execution: with the root registered, the page-load test passes on a fresh
   stack and in the full 247-spec suite; the new assertion pins the root so
   removing it fails the schema test (normalizePageRoute returns `"unknown"`).
2. `tests/e2e/workspace-capabilities-shell.spec.ts` — the happy-path test
   needs `config.write`, so it logs in as admin after `beforeEach` logged the
   same context in as PM. `App.tsx` has no `/login` route: `AuthGuard` wraps
   `/*` and renders the authenticated shell for any path once a session
   cookie exists, so the login form never mounts and `loginAsAdmin` timed out
   waiting on the username field. `clearCookies()` before `loginAsAdmin` is
   the minimal fix. Proven by execution: the spec passes 4/4 (including the
   redirect/no-revival tests) against a live hive.

## Known residual, out of scope

The "collector stored the observations" correlation test in
`rum-telemetry.spec.ts` fails in this local docker environment on both
attempts of a run: attempt 1 races the pagehide beacon's server-side persist
against the `limit=200` read-back, and attempt 2 fails structurally because
Playwright re-runs `beforeAll` (fresh empty `captured`) on retry without
re-running the page-load test whose flushes populate it. The same 2/2 failure
shape was recorded at base 41deb105ca by the prior repair run, so it is
pre-existing and unrelated to the page deletions; CI has never evidenced a
result at this head (the e2e-ui job was cancelled in the captured run).
