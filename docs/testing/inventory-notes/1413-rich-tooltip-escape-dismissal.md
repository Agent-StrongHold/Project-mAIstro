---
inventory-delta:
  packages/hive-conductor/tests/e2e: 0
---

# 1413-rich-tooltip-escape-dismissal

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

The delta is a truthful zero: `packages/hive-conductor/tests/e2e`'s recipe is
pytest collection (`bare_python=True`), which sees only the directory's Python
tests — Playwright specs never become collected node IDs, as
`issue-380-dashboard-kpi-metric-envelopes.md` already recorded when its own
`+7` e2e claim was corrected to nothing. No Python test was added or removed
by this change, so every measured suite count is unchanged.

What the change adds is `packages/hive-conductor/tests/e2e/
rich-tooltip-keyboard.spec.ts` — 4 Playwright tests proving #1413 (WCAG 1.4.13
Content on Hover or Focus) on the shipped `RichTooltip.tsx`. The component has
no consumer inside the SPA (the issue's own comment records that, and leaves
wire-or-retire as an open product decision), so the spec bundles the exact
shipped component into an ephemeral localhost page the same way
`dashboard-metrics-states.spec.ts` and `deck-sanitization.spec.ts` already
bundle the Dashboard and Deck Builder pages — `tests/Dockerfile.playwright`
gains one `COPY` line for the component, no new dependency. The four tests:
focus alone shows the tip and it stays shown while focus holds (the persistent
leg); Escape hides the tip while the trigger keeps focus (the dismissible leg,
and #1413's acceptance check); the dismissal latches against a re-hover until
the trigger is actually left and returns after blur + refocus; a repeat Escape
while hidden is a no-op and the hover/leave pointer path is unchanged.

The tests were shown to fail against the regression they name: the same spec
run against a scratch copy of `RichTooltip.tsx` with the Escape handler and
dismissal latch removed fails in the acceptance test itself (tooltip still
`visible` after Escape), with the serial suite halting there — while the
focus/persistence test still passes, because that behavior predates the fix.
Against the shipped component all 4 pass (4.3 s locally via the
`E2E_SRC_ROOT`/`E2E_NODE_PATHS` escape hatch, no app server needed).
