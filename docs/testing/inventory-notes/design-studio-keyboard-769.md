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

## Executed evidence (repair round 5, independent revalidation at 2df251b73)

Re-ran the acceptance battery at this head from the rebuilt sources:

- Frontend rebuilt from source (`npm run build`, tsc + vite clean) and served
  by `uvicorn main:app` on `HIVE_BASE_URL=http://127.0.0.1:8102` (setup-complete
  instance).
- `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts`:
  **6/6 passed (10.5s)** — tab-order selection of all 9 artifact modes with
  `aria-pressed` state, brief-gated editor entry (disabled → typed via keyboard
  → enabled), fixed-page layer/nudge journey, Deck editor → presentation
  dialog → Exit → focus restore, plus axe scans of the fixed-page editor, the
  Deck editor, and the open presentation dialog with no disabled rules and
  zero violations.
- `deck-sanitization.spec.ts`: **4/4 passed (2.8s)** via the CI-shaped staging
  (the `tests/Dockerfile.playwright` copy set staged under `E2E_SRC_ROOT` with
  the e2e standalone `react`/`react-dom` as `E2E_NODE_PATHS`).
- `uv run pytest packages/hive-conductor/backend/tests -q -k design`: **75
  passed**; `uv run ruff check .` and `uv run ruff format --check .` clean;
  `scripts/check-suite-inventory.py` exit 0 (13 suites);
  `scripts/check-frontend-api-routes.py` exit 0 (215 routes); frontend
  `npm run lint` 0 errors (90 pre-existing warnings).
- Lane boundary and focus re-checked in source: no lane commit touches
  `AppShell.tsx` or global shell CSS; DeckBuilder focuses its Exit button when
  the presentation opens and returns focus to the Present button on close
  (`presentationReturnRef`); FixedPageEditor exposes X/Y/W/H numeric inputs,
  8 px nudge buttons, and Move earlier/later with "dragging is never required"
  copy; visible focus comes from `button:focus-visible` (`src/index.css:600`).
- Prior finding E stays environmental/upstream: coincurve publishes no cp314
  wheels, so the hive image excludes the `[identity]` extra loudly
  (`packages/hive-conductor/Dockerfile:58-63`); not a #769 regression.

## Executed evidence (repair round 4, revalidation at 8e1b93882)

Re-ran the full battery against this head (backend: `uv run --no-project uvicorn
main:app` from `packages/hive-conductor/backend`, root venv, serving the freshly
rebuilt `frontend/dist` on `HIVE_BASE_URL=http://127.0.0.1:8102`):

- `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts`:
  6/6 passed (8.6s). The keyboard journey now also axe-scans the fixed-page
  editor, the Deck editor, and the open presentation dialog (probed first:
  all three surfaces report zero violations, then the scans were promoted
  into the shipped spec as regression guards).
- `deck-sanitization.spec.ts`: 4/4 passed (1.6s) via the CI-shaped harness
  layout (staged sources + standalone `react`/`react-dom` under
  `E2E_SRC_ROOT`/`E2E_NODE_PATHS`, matching `tests/Dockerfile.playwright`'s
  copy set; see the round-3 caveat below for why the raw worktree layout
  fails locally but not in CI).
- `uv run pytest packages/hive-conductor/backend/tests -q -k design`:
  75 passed; `uv run ruff check .` and `uv run ruff format --check .` clean;
  `scripts/check-suite-inventory.py` exit 0 (13 suites);
  `scripts/check-frontend-api-routes.py` exit 0 (215 routes); frontend
  `npm run build` (tsc + vite) and `npm run lint` (0 errors, 90/96 warnings)
  clean.
- Prior-round findings re-checked against this head and closed as stale:
  the editor-entry button is `disabled={!canOpenEditor}` (enabled by typing a
  brief, asserted by the keyboard journey), `/decks` is routed and the Deck
  editor opens from Design Studio, and the axe scan runs `.include("main")`
  with no disabled rules.

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
