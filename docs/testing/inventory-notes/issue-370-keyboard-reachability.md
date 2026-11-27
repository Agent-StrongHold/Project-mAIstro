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
- `narrow viewport keeps initial focus off the hamburger so the skip link
  stays first` — pins the Codex finding on PR #2530: at ≤900px the first
  render must not steal focus for the hamburger (that used to jump past the
  skip link), and the first Tab from <body> still lands on the skip link.

Sibling specs own the rest of the #370 surface: `agents-rsi-keyboard.spec.ts`
(RSI Stop + deleted-page redirects), `schedules-mcp-keyboard.spec.ts`
(schedule tabs/switch/presets + axe), `design-studio-keyboard.spec.ts`
(editor walks), `rich-tooltip-keyboard.spec.ts`, `modal-a11y.spec.ts`,
`workspace-a11y.spec.ts`, `toggle-switch-name.spec.ts`, and — added in the
post-review repair round — `dag-builder-keyboard-save-race.spec.ts`.

## Repair round: focus-restore transition + serialized keyboard saves

Two evidence-driven repairs landed after the first review pass, each with its
own regression journey:

- **AppShell drawer focus restore (Codex P2 on PR #2530).** The restore
  effect fired `menuButtonRef.current?.focus()` whenever `isMobile` held with
  the drawer closed — including the narrow viewport's first render, walking
  the user past the skip link before any interaction. The restore now runs
  only after an actual open→closed transition (`drawerWasOpenRef`). The
  narrow-viewport journey above pins it. The comment claiming an Escape
  close path was also corrected: the drawer closes via its close button,
  the overlay, and nav links — no Escape handler exists.
- **DAG Builder keyboard saves (`dag-builder-keyboard-save-race.spec.ts`).**
  Arrow-key node moves call `handleSaveDag` per keypress, so key-repeat fired
  overlapping PUTs whose out-of-order responses could roll the canvas back to
  a stale snapshot. Saves are now serialized and coalesced (≤1 in flight,
  callers mid-flight collapse into one trailing save with the latest
  snapshot; a failed chain drops its queued snapshot instead of replaying it
  stale). The spec asserts the structural contract, not wall-clock: max
  in-flight PUTs == 1 under a 400ms stub delay, the trailing save carries the
  final position, the failed-save path fires exactly two PUTs (failed +
  retry) and the canvas never shows the dropped stale frame.

## Executed evidence

All 19 keyboard journeys across the six keyboard specs pass (59/59 across the
whole keyboard/DAG/drawer/a11y cluster, and 236/236 across the full browser
suite in 3.4m) against a live hive backend built from this tree, driven the
way CI drives it: Playwright inside the `e2e-tests` container from
`docker-compose.test.yml`, against the `hive` service built from the same
sources. The click-only ratchet passes on the tree and fails CI-shaped when a
click-only `<div onClick>` is planted in `src/` (probe file, exit 1, removed
afterward).

The two new repair-round journeys were also shown to fail against the code
they fix, each on a purpose-built image: the narrow-viewport skip-link test
reports the hamburger focused on load with the old focus-restore effect
(exactly the Codex finding), and the save-race concurrency assertion fails
with the old per-keypress save path (4 overlapping PUTs under a 400ms stub
delay, against a max-in-flight of 1 with the fix).

Host-side Playwright runs (outside the e2e-tests container) are NOT the CI
execution mode: `rich-tooltip-keyboard.spec.ts` documents its local
`E2E_SRC_ROOT`/`E2E_NODE_PATHS` requirement, and the full-page axe scan in
`design-studio-keyboard.spec.ts` fails from the host browser while passing
8/8 in-container on both this tree and the develop base — a host
browser-environment artifact, not a product or branch regression (reproduced
against a base-commit build to prove attribution).

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
