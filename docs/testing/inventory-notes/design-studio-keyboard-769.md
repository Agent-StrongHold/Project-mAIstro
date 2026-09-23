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
