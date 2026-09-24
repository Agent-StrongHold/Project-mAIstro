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

## Executed evidence (repair round 7, merge reconciliation of develop base 60862b6c5)

The assigned develop base was merged into this lane. It carried #1486 (M1-C4
truthfulness rewrite that had disabled every Design Studio editor entry), the
#364/#66 HITL + Turing trust-boundary work, and the #311/#752 Deck sanitization
boundary. Three files conflicted; each was resolved as a union that keeps both
sides' contracts, then re-proven against a live stack:

- `packages/hive-conductor/frontend/src/pages/DesignStudio.tsx` — kept the
  brief-gated editor entry (`disabled={!canOpenEditor}`, line 245: enabled by
  typing, never permanently disabled), the fixed-page/Deck editor transitions
  with the textless focus anchor, and took develop's persisted-projects card
  verbatim (lines 210-232, including the 503 "Persisted Design projects are
  unavailable" messaging develop's new journey asserts).
- `packages/hive-conductor/frontend/src/pages/DeckBuilder.tsx` — kept the
  keyboard-complete ordered-page listbox, Move earlier/later, presentation
  dialog with focus management, and Save/Export controls; restored develop's
  `handlePreviewBlur` DOM-sanitization boundary (line 124) and `onDragOver`
  prevention (line 146). The missing `onDragOver` was caught by a real failing
  deck-sanitization test during this round's validation and fixed — the
  sanitization boundary from #752 and the keyboard surface from #769 now ship
  in one component.
- `packages/hive-conductor/tests/e2e/design-studio-truthfulness.spec.ts` —
  both develop's "reports unavailable persistence instead of an empty durable
  state" journey (line 232) and the keyboard-safe contained-Deck journey (line
  256, URL asserted to stay on `/cli/canvas`).

Validation re-run at this merged head:

- Frontend `npm run build` (tsc + vite) clean; `npm run lint` 0 errors (90
  pre-existing warnings); `uv run ruff check .` and `uv run ruff format
  --check .` clean; `scripts/check-suite-inventory.py` exit 0 (13 suites);
  `scripts/check-frontend-api-routes.py` exit 0 (216 routes).
- Backend: `pytest packages/hive-conductor/backend/tests -q -k design` → **82
  passed**; `-k "hitl or workspace or credential or registered_dag"` → **317
  passed**; `packages/maistro-design/tests` + `packages/maistro-turing` (src
  and backend) + `tests/test_credential_authority.py` → **576 passed**;
  `packages/maistro-core/tests/graph/durable_runs` +
  `packages/maistro-core/tests/security` → **1766 passed, 40 skipped**. One
  environmental failure, pre-existing and confirmed identical on the develop
  base clone (57ddca502):
  `packages/maistro-core/tests/security/test_log_redaction.py::
  test_install_is_idempotent` fails under pytest 9.1.1's logging plugin
  (passes with `-p no:logging`); the module is untouched by this lane and by
  the merge.
- Live e2e — backend `uv run --no-project uvicorn main:app` serving the
  freshly rebuilt `frontend/dist` on 127.0.0.1:8102 (`GET /v1/setup/status` →
  `setup_complete: true`): `design-studio-keyboard.spec.ts` +
  `design-studio-truthfulness.spec.ts` **7/7 passed (9.3s)**;
  `deck-sanitization.spec.ts` **7/7 passed (2.1s)** via the CI-shaped
  `E2E_SRC_ROOT`/`E2E_NODE_PATHS` staging copied from
  `tests/Dockerfile.playwright`.

Driver findings disposition, re-verified against this merged head:

- "inventory-delta mapping malformed / check-suite-inventory exits 2" — stale;
  the front matter parses and the checker exits 0 (13 suites).
- "DesignStudio.tsx permanently disables the only generation/editor entry;
  generation/editing/export unavailable" — true only of the develop base's
  #1486 containment. The merged page's entry is brief-gated (line 245) and the
  real editors open; asserted by keyboard journey test 3 and truthfulness
  journey test 6 against the live app.
- "App.tsx redirects the Deck route; Open Deck editor disabled" — stale;
  `App.tsx:195` routes `/decks` (M0 containment lifted) and `AppShell.tsx` is
  untouched by the merge resolution.
- "keyboard spec only scans the picker parent; excludes color-contrast" —
  stale; the spec scans `main` with no disabled rules and full-page scans run
  inside both editors (all green in this round's runs).
- "docker compose build fails (coincurve metadata under Python 3.14)" —
  upstream cp314 wheel gap, loudly excluded via the `[identity]` extra in
  `packages/hive-conductor/Dockerfile`; not a #769 regression. This round's
  e2e evidence was produced by running the stack directly instead of compose.

## Executed evidence (repair round 6, independent revalidation at 516b7357)

Re-ran the acceptance battery at this head (worktree `/home/dev/Git/wt/auto-769`):

- Frontend rebuilt from source (`npm run build`, tsc + vite clean, 3.5s) and
  served by `uv run --no-project uvicorn main:app` from
  `packages/hive-conductor/backend` on port 8102 (persisted setup-complete
  instance at `~/.conductor`; `GET /v1/setup/status` → `setup_complete: true`).
- `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts`:
  **6/6 passed (11.4s)** against the live routed app — tab-order selection of
  all 9 artifact modes with `aria-pressed` state, brief-gated editor entry,
  fixed-page add-layer/nudge journey with a full-page axe scan, Deck editor →
  presentation dialog → Exit, plus the catalog-degradation journey.
- `deck-sanitization.spec.ts`: **4/4 passed (1.8s)** with the
  `tests/Dockerfile.playwright` copy set staged under `E2E_SRC_ROOT` and the
  e2e standalone `react`/`react-dom` as `E2E_NODE_PATHS`.
- `uv run pytest packages/hive-conductor/backend/tests -q -k design`:
  **75 passed** in 5.5s; `uv run ruff check .` clean; `uv run ruff format
  --check .` clean (2528 files); `scripts/check-suite-inventory.py` **exit 0**
  (13 suites — the note front matter parses and `packages/hive-conductor/
  tests/e2e` collects 23 nodes as recorded); `scripts/check-frontend-api-
  routes.py` exit 0 (215 routes); frontend `npm run lint` 0 errors (90
  pre-existing warnings).
- Prior verifier findings re-checked against this head, all stale or
  non-lane: no `disabled`-forever editor entry exists (entry is
  `disabled={!canOpenEditor}`, enabled by typing a brief — DesignStudio.tsx
  `openEditor`); `/decks` is routed (`App.tsx` `<Route path="decks">` with
  M0 containment lifted) and the Deck editor opens from Design Studio; the
  keyboard spec's axe scans run with **no disabled rules** (the only
  `color-contrast` exclusions in the e2e tree are in `credential-labels` and
  `modal-a11y`, which are different features); the coincurve/cp314 compose
  failure is the loudly-documented `[identity]` exclusion in
  `packages/hive-conductor/Dockerfile` (upstream wheel gap, SPEC-072726-3439),
  not a #769 regression.
- Lane boundary re-checked via `git show --stat` on every lane commit
  (bb4e24375, 2df251b73, 8e1b93882, c6d068d3e): only Design-Studio pages,
  e2e specs, and this note changed. `AppShell.tsx` untouched; visible focus
  ships from the shell's `button:focus-visible` rule (`src/index.css:600`).

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
