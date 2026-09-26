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
API tests). The routed `/decks` journey added in repair round 12 grows the
browser corpus, not the pytest ledger, so the delta stays `+0`.

## Executed evidence (repair round 12, routed /decks coverage + Deck focus fixes)

Round 11's verification pass returned NEEDS-REPAIR with four actionable
findings (the fifth, `test_pm_workflow_api.py` fixture errors, is
pre-environmental and out of lane). This round fixes all four in source and
re-executes the affected journeys against a live server:

- `DeckBuilder.tsx` contentEditable carried a bare `outline: "none"` with no
  focus-visibility rationale (axe does not scan WCAG 2.4.7). Fixed for real:
  focus is tracked in React state and the focused editor draws a 2px accent
  outline (inline styles cannot express `:focus-visible`). The routed journey
  now asserts the computed outline is drawn while focused.
- Writing that assertion exposed a genuine focus-management defect: on
  presentation exit, `presentationReturnRef` held the *detached* Present
  button node (the editor unmounts while presenting), so the restore effect
  silently no-op'd and keyboard focus fell to `body`. The component now keeps
  a live ref on the Present button plus a restore-intent ref (so the editor's
  first mount never steals focus) and re-resolves the node after remount.
  The routed journey asserts `Present` is focused again after Escape.
- The routed `/decks` surface had zero browser coverage and the spec comment
  in `deck-sanitization.spec.ts` claimed journeys covered it. Added a
  keyboard-only journey to `design-studio-keyboard.spec.ts` that goes to
  `/decks` directly, Tab-walks from the page top to the ordered-page listbox,
  selects/adds/reorders slides with Enter on native buttons, checks the
  visible focus indicator, runs two full-page axe scans (editor and
  presentation dialog, shell included, no `disableRules`), drives slide
  advance with ArrowRight/ArrowLeft/PageDown/PageUp and the Previous/Next
  slide buttons against the "Slide N of M" live region, and exits with
  Escape to the restored focus. The sanitization comment now names the spec
  that really covers `/decks`.
- Executed: `npm run build` (tsc + vite) clean; `npm run lint` 0 errors
  (90 pre-existing warnings); `uv run ruff check .` and
  `uv run ruff format --check .` clean; `uv run pytest
  packages/hive-conductor/backend/tests -q -k design` → **82 passed**.
- Live e2e, executed this round: backend `uvicorn main:app` on 127.0.0.1:8102
  serving the freshly rebuilt `frontend/dist` (`/v1/setup/status` →
  `setup_complete: true`; `GET /decks` → 200).
  `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts` →
  **8/8 passed (13.8s, includes the new routed journey)**;
  `deck-sanitization.spec.ts` → **7/7 passed (3.0s)** via the
  `tests/Dockerfile.playwright`-shaped staging dir with the real (changed)
  `DeckBuilder.tsx` copied in — the sanitizer boundary still holds.
- Vulture per-identity gate re-checked for the CI-repair clause:
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → exit 0, 1414 reviewed identities, 0 unclassified, no
  ledger amendment needed.

## Executed evidence (verification round 10, independent revalidation at merged head 1dfccece)

Round 9's agent run died on the wall-clock deadline before reporting; this
round re-derived every acceptance criterion at the new head — the merge of
develop base `55c5ad892` into `auto-769` (`1dfccece8`, clean tree) — without
trusting any prior round's claims:

- Round-0 driver findings re-checked in source, all still stale at this head:
  the note front matter parses (`check-suite-inventory.py` exit 0, 13 suites);
  the editor entry is `disabled={!canOpenEditor}` (DesignStudio.tsx:245,
  brief-gated, Availability card reports editing/presentation/export
  available); `App.tsx` routes `/decks` under the containment-lifted comment;
  the keyboard spec's three axe scans (`:150` scoped to `main`, `:166`/`:177`
  full-page inside the fixed-page editor and the Deck presentation dialog)
  carry no `disableRules`.
- Executed this round: `uv run ruff check .` clean; `npm run build` (tsc +
  vite) clean; `uv run pytest packages/hive-conductor/backend/tests -q -k
  design` → **82 passed** (5.6s); `scripts/check-suite-inventory.py` → exit 0
  (13 suites); `scripts/check-frontend-api-routes.py` → exit 0 (217 routes
  across 61 call-site files).
- Live e2e, executed this round: `uv run --no-project uvicorn main:app` from
  `packages/hive-conductor/backend` serving the freshly rebuilt
  `frontend/dist` on 127.0.0.1:8102 (`GET /v1/setup/status` →
  `setup_complete: true`; `GET /cli/canvas` → 200).
  `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts` →
  **7/7 passed (11.7s)**; `deck-sanitization.spec.ts` → **7/7 passed (3.1s)**.
  Server stopped after the run; tree left clean.
- Local-staging correction for `deck-sanitization.spec.ts`: pointing
  `E2E_SRC_ROOT` at the real worktree fails with a blank harness page because
  `frontend/node_modules` (react 19.2.6) shadows the standalone copy
  (react 19.2.0) for DeckBuilder's own imports while the temp entry resolves
  react via `E2E_NODE_PATHS` — two React copies, "Invalid hook call". This is
  a staging mistake, not a product or spec defect: CI's
  `tests/Dockerfile.playwright` copies the sources next to a single
  `node_modules`, and the round's green run used exactly that shape (staging
  dir with the Dockerfile's copy set + the e2e standalone `node_modules`
  symlinked as its `node_modules`, `E2E_SRC_ROOT`/`E2E_NODE_PATHS` pointing
  there). Use the Dockerfile-shaped staging dir, never the worktree, as
  `E2E_SRC_ROOT`.
- The compose-build failure in the round-0 findings remains the documented
  upstream coincurve cp314 gap (`packages/hive-conductor/Dockerfile:58-63`,
  SPEC-072726-3439), not a #769 regression; this round's e2e evidence was
  produced by running the stack directly.
- Lane boundary and closure hygiene: `git diff --name-only
  55c5ad892..1dfccece8` touches only the 10 lane files (Design Studio/Deck
  editors, e2e specs, e2e package files, this note); `AppShell.tsx` and global
  shell CSS are untouched, and neither the PR body ("Refs #769") nor any lane
  commit message carries fixes/closes/resolves keywords.

## Executed evidence (repair round 9, independent revalidation at 9841ae58f)

Re-ran the whole battery at the current head (`9841ae58f`, clean tree, no tree
edits this round) after the round-8 run died on a provider timeout:

- Round-0 findings re-checked in source, all still stale: the note front
  matter parses (`check-suite-inventory.py` exit 0, 13 suites); the editor
  entry is `disabled={!canOpenEditor}` (DesignStudio.tsx:245, brief-gated,
  `role="status"` state at :246) with the Availability card reporting
  editing/presentation/export available; `App.tsx:195` routes `/decks` with
  the containment-lifted comment; the keyboard spec's three axe scans (main-
  scoped and two full-page inside the editors) carry no `disableRules`.
- `uv run ruff check .` + `uv run ruff format --check .` → clean (2533 files);
  `uv run pytest packages/hive-conductor/backend/tests -q -k design` →
  **82 passed**; `npm run build` (tsc + vite) → clean; `npm run lint` →
  0 errors (90 warnings); `scripts/check-frontend-api-routes.py` → exit 0
  (216 routes across 61 call-site files).
- Live e2e re-executed: `uv run --no-project uvicorn main:app` serving the
  rebuilt `frontend/dist` on 127.0.0.1:8102 (`GET /v1/setup/status` →
  `setup_complete: true`, `GET /cli/canvas` → 200).
  `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts` →
  **7/7 passed (11.1s)**; `deck-sanitization.spec.ts` → **7/7 passed (2.4s)**
  via the `tests/Dockerfile.playwright`-shaped staging. Local-staging note:
  the standalone `node_modules` copy must now include `scheduler` (a react-dom
  19.2 transitive dep) alongside `react`/`react-dom`, or the esbuild bundle
  fails with `Could not resolve "scheduler"` — CI's `npm install` image is
  unaffected. Server stopped after the run; tree left clean.
- The compose-build failure in the round-0 findings is the documented upstream
  coincurve cp314 gap (`packages/hive-conductor/Dockerfile:58-63`,
  SPEC-072726-3439), not a #769 regression; the lane boundary still holds —
  `git diff --name-only 60862b6c5..HEAD` touches neither `AppShell.tsx` nor
  `index.css` (the `button:focus-visible` outline at index.css:600-604
  pre-exists).

## Executed evidence (repair round 8, independent re-admission validation at ad7245a78)

Re-derived every acceptance criterion at the merged head (clean tree,
`ad7245a78`) without trusting prior rounds' claims:

- `scripts/check-suite-inventory.py` → exit 0, 13 suites match (the note front
  matter parses; the round-0 "malformed inventory-delta" finding is stale).
- `uv run ruff check .` + `uv run ruff format --check .` → clean (2533 files).
- `uv run pytest packages/hive-conductor/backend/tests -q -k design` →
  **82 passed**; `scripts/check-frontend-api-routes.py` → exit 0 (216 routes
  across 61 call-site files); `npm run build` (tsc + vite) → clean.
- Live e2e, executed this round: `uvicorn main:app` from
  `packages/hive-conductor/backend` serving the freshly rebuilt
  `frontend/dist` on 127.0.0.1:8102 (`GET /v1/setup/status` →
  `setup_complete: true`, `GET /cli/canvas` → 200).
  `design-studio-keyboard.spec.ts` + `design-studio-truthfulness.spec.ts` →
  **7/7 passed (10.9s)**, including the all-9-modes tab-order journey with
  `aria-pressed` selection state, the fixed-page add-layer/move-right journey,
  and the Deck editor → presentation → Exit journey. `deck-sanitization.spec.ts`
  → **7/7 passed (2.6s)** via the `tests/Dockerfile.playwright`-shaped staging
  (`E2E_SRC_ROOT` + e2e standalone `E2E_NODE_PATHS`).
- Source re-inspection of the round-0 findings, all stale at this head:
  the editor entry is `disabled={!canOpenEditor}` (DesignStudio.tsx:245,
  brief-gated — enabled by typing, with `role="status"` announcement); the
  Availability card reports editing/presentation/export as available;
  `App.tsx:195` routes `/decks` (containment lifted, comment cites #752/#769);
  the keyboard spec's axe scans (`:150` scoped to `main`, `:166`/`:177`
  full-page inside the editors) carry **no `disableRules`** — color-contrast
  is included; `packages/hive-conductor/Dockerfile:58-63` documents the
  coincurve cp314 wheel gap loudly (upstream, SPEC-072726-3439), so the
  compose-build failure is not a #769 regression.
- Keyboard-equivalents re-verified in source: DeckBuilder ordered-page
  listbox (`role="option"` + `aria-selected`, Move earlier/later,
  "no drag operation is required" help), presentation Arrow keys with
  `presentationReturnRef` focus restore, Export HTML/Print as native buttons;
  FixedPageEditor nudge + X/Y/W/H property inputs and Move earlier/later with
  "dragging is never required" copy; visible focus ships from the shell's
  `button:focus-visible` outline (`frontend/src/index.css:600-604`).
- Lane boundary: `git diff --stat 60862b6c5..HEAD` touches only the 10 lane
  files (Design Studio/Deck editors, e2e specs, e2e package files, this note);
  `AppShell.tsx` and global shell CSS are untouched.

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
