---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# Issue 370 keyboard reachability

The `+0` delta is intentional: this change adds browser-only `*.spec.ts`
journeys, which pytest never collects, so the suite's pytest node count (the
`test_pm_workflow_api.py` API tests) does not move.

The keyboard journey inventory for the Conductor primary surfaces now lives in
`packages/hive-conductor/tests/e2e/keyboard.spec.ts`. That path is the one the
`hive-conductor-e2e-ui` CI job actually executes: `tests/Dockerfile.playwright`
copies `tests/e2e/` into the image and runs
`npx playwright test --config=tests/e2e/playwright.config.ts`, so every spec
in that directory is collected.

The previous `frontend/e2e/keyboard.spec.ts` was run by **no** workflow — the
frontend package's Playwright command is not referenced by any CI job — so its
five journeys were dead code that had never been executed. It has been removed
and its journeys ported to the CI-collected location. Because the dead spec had
never run, several of its assertions encoded behaviour the implementation did
not actually have; porting them surfaced and fixed real defects rather than
transcribing passing tests:

- **Chat model menu did not return focus.** The dead spec asserted that
  selecting an option left focus on the model button. The implementation closed
  the menu and dropped focus to `<body>`, so the next Tab restarted at the top of
  the page. `Chat.tsx` now moves focus onto the selected option when the menu
  opens, restores focus to the trigger on selection, and closes on Escape.
- **Setup journey could not advance.** The dead spec focused the wizard's "next"
  button without first filling the required conductor name, so it focused a
  disabled button and pressed Enter on nothing. The ported journey fills the
  name first.
- **Credentials "save" was asserted reachable while disabled.** The per-provider
  save button is disabled until a value is entered, so it is correctly absent
  from the tab order; the journey now asserts the always-reachable reveal toggle
  and token input.
- **The /agents journey assumed a seeded roster.** The ported suite's
  `/agents` leg expected the per-agent `Open … details` button, but a cold
  hive has zero agents, so the control never rendered and the journey failed
  the moment it ran against a real backend. The journey now seeds one agent
  through an isolated admin API request context (the PM principal only holds
  `dags.write`), then walks the tab order — asserting a real row control
  instead of skipping it the way a fresh install silently would.

## What the ported suite covers

- `skip link is the first tab stop and moves focus to the main landmark` —
  walks from `<body>` and proves the skip link is reachable and that Enter
  moves focus into `main#main-content`.
- `chat model menu is operable without a pointer and returns focus` — opens,
  selects, and closes the model menu by keyboard alone.
- `schedule view tabs are native keyboard controls` — switches schedule/history
  views and toggles the enable switch when a schedule exists.
- `primary page controls are reachable in the real tab order` — records `focusin`
  across a full Tab walk and asserts representative controls on `/agents`,
  `/mcp`, `/credentials`, `/rsi`, and `/cli/canvas` are reachable. This is the
  stronger half: `.focus()` proves a control is focusable, the Tab walk proves
  it is *reachable*.
- `setup step navigation and hardware choices are buttons` — fills the required
  name, advances the wizard, and selects a hardware preset.

The Design Studio parent-surface journey remains in
`tests/e2e/design-studio-keyboard.spec.ts` and is unchanged.

## Executed evidence

All five journeys pass (5/5, ~10s) against the branch's own frontend build
served by a live hive backend, walked with a real Chromium — including the
full Tab-order leg over `/agents`, `/mcp`, `/credentials`, `/rsi`, and
`/cli/canvas`. The click-only ratchet (`npm run check:keyboard`) passes on the
tree and was proven to fail CI-shaped when a click-only `<div onClick>` is
planted in `src/`.

## Reviewed exceptions

- Backdrop click handlers only dismiss an already-open drawer or modal; the same
  surfaces have a close button and Escape behavior, and are excluded from the
  click-only control ratchet with `aria-hidden="true"`.
- Design Studio's generation action remains disabled because durable execution is
  not connected; its visible status text explains that no submission occurs.
- The per-provider credentials save button is disabled until a value is entered,
  so it is intentionally not in the tab order.
