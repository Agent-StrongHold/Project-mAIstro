---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# Design Studio keyboard journey (#769)

Adds Playwright journeys that walk every supported Design Studio artifact mode
from the real page tab order, activate native controls with keyboard commands,
and verify fixed-page and Deck editor transitions. The mode journey also runs
axe against the page's main landmark without excluding color contrast.
The `+0` delta is intentional: these browser-only `*.spec.ts` journeys are not
collected by pytest, so their node count is not part of the inventory ledger
(the suite's 23 collected nodes are the pre-existing `test_pm_workflow_api.py`
API tests).

## Executed evidence (repair round 3, post-merge revalidation at 2845e1c98)

After the develop merge, all journeys were re-executed against the same
worktree's sources. Backend: `uvicorn main:app` serving the rebuilt
`frontend/dist` on `HIVE_BASE_URL=http://127.0.0.1:8102` (the root workspace
venv plus an editable `maistro-design` install satisfies the backend's
imports). Frontend: `npm run build` (tsc + vite) — clean.

- `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts`:
  6/6 passed (9.7s) against the live routed app.
- `deck-sanitization.spec.ts`: 4/4 passed (1.8s). Local-run note: the spec
  bundles the real DeckBuilder sources, so run it with `E2E_SRC_ROOT` /
  `E2E_NODE_PATHS` pointed at a CI-shaped tree — if `frontend/node_modules`
  is reachable from `E2E_SRC_ROOT`, esbuild bundles a second React copy and
  the hooks blow up. CI's image copies only the listed sources, so it is
  unaffected.
- `scripts/check-suite-inventory.py` exit 0 (13 suites);
  `scripts/check-frontend-api-routes.py` exit 0; ruff check/format clean;
  frontend eslint 0 errors; 68 design-route backend tests pass; the
  `packages/hive-conductor/Dockerfile` image builds (its comments document
  why the [identity]/coincurve extra is excluded on the Python 3.14 base).

## Executed evidence (repair round 2)

After resolving the develop merge (28732d5ed), the journeys were executed for
real against a live stack — `uvicorn main:app` (backend serving
`frontend/dist`) on `HIVE_BASE_URL=http://127.0.0.1:8102`, Chromium via the
repo's Playwright config:

- `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts`:
  6/6 passed (8.2s).
- `deck-sanitization.spec.ts` (#752 boundary proof, re-bundled from the merged
  DeckBuilder sources): 4/4 passed (1.6s).

Fixes made while getting the journeys green (all in-lane files):

- Design Studio rendered a duplicate `h1` "Design Studio" next to PageHeader's;
  the page now keeps one heading plus a textless focus anchor, and its root is
  a labelled `div` instead of a nested `main` landmark (axe
  `landmark-main-is-top-level`). DeckBuilder and FixedPageEditor roots got the
  same nested-`main` treatment.
- The truthfulness journey now selects the Infographic artifact mode before
  opening its editor (it previously assumed a mode the user never chose).
- The keyboard journey asserts the editor entry is disabled before a brief
  exists and enabled after typing one, and scopes status assertions to the
  editor's own status region.
- The keyboard journey's visible-text assertions were realigned with the
  shipped help copy ("Keyboard: Tab moves between artifact types…", "Enter a
  brief, then open the keyboard-complete editor…").
