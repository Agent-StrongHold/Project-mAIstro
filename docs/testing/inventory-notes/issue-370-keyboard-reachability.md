---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# Issue 370 keyboard reachability

The `+0` delta is intentional: this change adds browser-only `*.spec.ts`
journeys, which pytest never collects, so the suite's pytest node count (the
`test_pm_workflow_api.py` API tests) does not move.

The keyboard journey inventory for the Conductor primary surfaces lives in
`packages/hive-conductor/tests/e2e/keyboard.spec.ts`. That path is the one the
`hive-conductor-e2e-ui` CI job actually executes: `tests/Dockerfile.playwright`
copies `tests/e2e/` into the image and runs
`npx playwright test --config=tests/e2e/playwright.config.ts`, so every spec
in that directory is collected.

## Rebase onto the Workspace-cutover frontend

The keyboard work was rebased onto the merged Workspace switchover (#1495) and
the page retirements that followed it (#2273 Agents/MCP/Skills/Topology,
#2274 Dashboard, #1049 MessageBoard). Journeys that targeted deleted pages now
walk their successors; coverage that lives in a sibling spec is not duplicated:

- skip-link leg: `/dashboard` → `/home` (the legacy URL now redirects there).
- the `/agents` and `/mcp` tab-order legs → `/capabilities` (the one capability
  surface); the agent-seeding block left with the Agents builder module, whose
  redirect contract `agents-rsi-keyboard.spec.ts` pins.
- the schedule view-tab leg dropped: `schedules-mcp-keyboard.spec.ts` covers
  the tabs/switch contract with a deterministic API mock and an axe scan.
- the `/cli/canvas` leg → covered by `design-studio-keyboard.spec.ts` (the
  implementation-era path now only redirects to `/design-studio`).
- the `/rsi` leg walks an admin session in its own context, because #373 gates
  `/rsi` behind `PermissionBoundary("rsi.execute")` (same arrangement as
  `agents-rsi-keyboard.spec.ts`).
- Chat's model-menu journey pins the workspace-scoped page (#1822): the
  context persists an active workspace id so the model selector mounts, and
  `/v1/models` is served a deterministic catalog so the journey does not
  depend on gateway discovery.

The click-only ratchet (`frontend/scripts/check-keyboard-controls.mjs`,
chained into `npm run lint`) survives the cutover and now also fails on the
new surfaces' click-only elements — which is exactly what happened, and why
`Backlog.tsx` (board/list tabs, entry titles, dependency badges),
`Setup.tsx` (wizard steps, hardware presets), and `Schedules.tsx` were
resolved onto keyboard-operable controls rather than left as merge-blocking
debt.

## What the suite covers

- `skip link is the first tab stop and moves focus to the main landmark` —
  walks from `<body>` on `/home` and proves the skip link is reachable and
  that Enter moves focus into `main#main-content`.
- `chat model menu is operable without a pointer and returns focus` — opens,
  selects, and closes the model menu by keyboard alone; selecting and Escape
  both land focus back on the trigger.
- `primary page controls are reachable in the real tab order` — records
  `focusin` across a full Tab walk and asserts representative controls on
  `/capabilities`, `/credentials`, and `/rsi` are reachable. This is the
  stronger half: `.focus()` proves a control is focusable, the Tab walk proves
  it is *reachable*. Data-dependent controls (capability-slot Enable/Disable)
  are asserted only when their data is present.
- `setup step navigation and hardware choices are buttons` — fills the
  required name, acknowledges the gateway-unverified gate when it renders,
  advances the wizard, and selects a hardware preset.

Sibling specs own the rest of the #370 surface: `agents-rsi-keyboard.spec.ts`
(RSI Stop + deleted-page redirects), `schedules-mcp-keyboard.spec.ts`
(schedule tabs/switch/presets + axe), `design-studio-keyboard.spec.ts`
(editor walks), `rich-tooltip-keyboard.spec.ts`, `modal-a11y.spec.ts`,
`workspace-a11y.spec.ts`, `toggle-switch-name.spec.ts`.

## Executed evidence

All 16 keyboard journeys across the five keyboard specs pass (16/16, ~17s)
against a live hive backend built from this tree, walked with a real Chromium.
The full browser suite — 233 specs — passes 233/233 on a fresh hive. The
click-only ratchet passes on the tree and fails CI-shaped when a click-only
`<div onClick>` is planted in `src/` (observed on the pre-resolution merge,
which reported the exact Backlog/Schedules/Setup violations listed above).

## Reviewed exceptions

- Backdrop click handlers only dismiss an already-open drawer or modal; the same
  surfaces have a close button and Escape behavior, and are excluded from the
  click-only control ratchet with `aria-hidden="true"`.
- Design Studio's generation action remains disabled because durable execution is
  not connected; its visible status text explains that no submission occurs.
- The per-provider credentials save button is disabled until a value is entered,
  so it is intentionally not in the tab order.
- Two `<main>` landmarks exist on `/dags` (the shell's `main#main-content` and
  the page's own `<main>`), inherited from develop's page markup; retiring the
  page-level `<main>` is page-surface work tracked with the Workspace cutover,
  not this issue's control-reachability scope.
