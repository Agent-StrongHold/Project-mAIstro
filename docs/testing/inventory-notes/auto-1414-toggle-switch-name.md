---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# #1414 Toggle switch announces name and checked state

Adds `packages/hive-conductor/tests/e2e/toggle-switch-name.spec.ts`: it mounts
the real `Toggle` component from
`packages/hive-conductor/frontend/src/components/shared.tsx` on an ephemeral
localhost page (the `deck-sanitization.spec.ts` esbuild-harness pattern) and
asks the browser's accessibility tree whether the `role="switch"` resolves by
its visible label, whether `aria-checked` tracks clicks, and whether the name
is carried by the button's own `aria-label` — plus a non-vacuity guard where a
nameless raw switch on the same page must be rejected by axe `button-name`.

Two source changes ride along:

- `shared.tsx`: `Toggle`'s `label` prop is required, not optional. React
  omits `aria-label` when the value is undefined, so an optional label let a
  consumer silently render an unnamed switch. `Toggle` has zero consumers
  (verified across the tree), so the tightening breaks nothing.
- `tests/Dockerfile.playwright`: one `COPY` line bringing `shared.tsx` into
  the CI image, which previously copied only the files the deck/dashboard
  harnesses import.

The `+0` delta is intentional: the suite is TypeScript Playwright, not part
of the pytest collection inventory (same shape as
`752-deck-sanitization-hardening.md`); `scripts/check-suite-inventory.py`
still passes with all 17 recorded suites unchanged.

## Validation evidence

- `npx playwright test toggle-switch-name` (chromium, local): 3 passed.
- Sensitivity check: a copy of `shared.tsx` with the `aria-label={label}`
  line removed (reverting the merged #1504 fix) makes the spec fail at
  `toHaveAttribute("aria-label", ...)`. The announcement-only assertions do
  NOT fail in current Chromium — engines now derive a name from the wrapping
  `<label>` — which is why the spec pins the explicit mechanism separately
  from the announcement.
- `tsc -p tsconfig.json --noEmit` and `tsc -p tsconfig.node.json --noEmit`
  in `packages/hive-conductor/frontend`: exit 0.
- `npm run lint` in the frontend: 0 errors, 94 warnings (limit 96); the one
  warning touching `shared.tsx` (`react-hooks/set-state-in-effect`, line
  ~357) is pre-existing and outside the changed block.
- `uv run ruff check .` / `uv run ruff format --check .`: clean.
- `uv run python scripts/check-suite-inventory.py`: ok, 17 suites match.
