---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---
# Design Studio route cutover (#95, M3-B5 product IA slice)

Cuts the shipped product information architecture over to Design Studio as the
parent creative-production surface: the canonical deep link is
`/design-studio`, the surface is a first-class primary navigation entry, and
the implementation-era `/cli/canvas` route is retired to a compatibility
redirect. Backend capability namespaces (`/v1/canvas/**`, `/v1/design/**`) are
untouched — the route namespace is product identity, not API identity
(SPEC-070226-8239, ADR-045).

The `+0` deltas are intentional: the two new journeys are Playwright
`*.spec.ts` tests (browser corpus, not pytest-collected — same reasoning as
`design-studio-keyboard-769.md`), and no backend Python tests moved.

## Changes

- `packages/hive-conductor/frontend/src/App.tsx` — `design-studio` renders the
  Design Studio page; `cli/canvas` renders `<Navigate to="/design-studio"
  replace />` so old deep links land on the canonical route without a second
  product identity.
- `packages/hive-conductor/frontend/src/components/AppShell.tsx` — Design
  Studio added to `fullNav` (Palette icon, after Dashboard), so primary
  navigation (drawer + icon sidebar) deep-links the canonical route.
- `packages/hive-conductor/tests/e2e/design-studio-truthfulness.spec.ts` — all
  journeys enter via `/design-studio`; the Deck-mode URL assertion expects
  `/design-studio`; two new tests: `/cli/canvas` compatibility redirect, and
  primary-navigation deep link from `/dashboard` through the icon sidebar.
- `packages/hive-conductor/tests/e2e/design-studio-keyboard.spec.ts` — the
  three product-surface journeys enter via `/design-studio`.
- `packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts` — header
  comment route rename only.
- `KNOWN-GAPS.md` — the Design Studio entry records the landed IA cutover and
  keeps the remaining gaps truthful (generation disabled, server-side
  publish/export absent, browser-local artifact state, Canvas store 503 in the
  shipped `maistro-server`).

## Executed evidence (2026-09-29, worktree auto-95 @ 04c1b9636 + this slice)

- `npm run build` in `frontend/` (tsc both tsconfigs + vite) → exit 0;
  `DesignStudio-DuoTrCO4.js` chunk still code-split.
- `npm run lint` → exit 0 (0 errors, 96 warnings; no warning in the changed
  files — the `App.tsx` 56:14 react-refresh warning predates this slice).
- Live stack from this worktree: `uvicorn main:app` (workspace venv,
  `PYTHONPATH` including `packages/maistro-design/src`, scratch
  `CONDUCTOR_DATA_DIR=/tmp/hive95-state`) serving the freshly built
  `frontend/dist` on 127.0.0.1:8202; fresh boot reported
  `setup_complete: false` and the e2e setup wizard provisioned it.
- `HIVE_BASE_URL=http://127.0.0.1:8202 npx playwright test
  design-studio-truthfulness.spec.ts design-studio-keyboard.spec.ts
  route-code-splitting.spec.ts` → **12/12 passed (53.9s)**, including
  `/cli/canvas is a compatibility redirect to the canonical Design Studio
  route` and `primary navigation deep-links the canonical Design Studio
  route`.
- `deck-sanitization.spec.ts` → **9/9 passed (18.0s)** via the
  `tests/Dockerfile.playwright`-shaped staging dir (`E2E_SRC_ROOT` at a copy of
  `frontend/src` beside the standalone e2e `node_modules`; the first attempt
  pointed `E2E_SRC_ROOT` at the worktree and hit the documented two-React
  resolution failure — staging mistake, not a product defect; see
  `design-studio-keyboard-769.md` round 9).
- `python -m pytest tests -q -k design` (backend, workspace venv, bare python)
  → **83 passed** in 245.8s. Note for the next runner: invoking this battery
  through `uv run pytest` from the repo root hung in startup twice on this
  machine; the direct `.venv/bin/python -m pytest` invocation from
  `packages/hive-conductor/backend` is the reliable shape here.
- Server stopped after the runs; worktree carries only the slice files above.

## Not claimed by this slice

The remaining #95 acceptance criteria stay open and are not evidenced here:
the #851 Canvas store/API/lease/migration operability floor (shipped
`maistro-server` still does not inject the Canvas store, so mounted data
routes return 503), server-side durable project/execution restore (fixed-page
artifacts remain browser-local), a launched non-Canvas specialized tool
boundary beyond Deck (#773), and the full product E2E closure of the
KNOWN-GAPS entry.
