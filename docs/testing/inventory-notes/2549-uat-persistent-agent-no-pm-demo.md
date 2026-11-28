---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# 2549-uat-persistent-agent-no-pm-demo

UAT direction (#2549): the product must not carry PM-demo heritage in its
first-run UX, and the persistent Workspace Agent becomes the primary surface
on every page.

What moved, and why the net is five:

- **+5** in the new `backend/tests/test_pm_tooling_module_gate.py`: the
  `pm_fleet` persona is picker-gated behind the explicit `pm_tooling`
  optional module. The cases pin both directions (hidden without the module,
  restored once setup selects it), the installed-base guarantee (a pre-gate
  `pm_fleet` workspace still resolves; per-template agent routes stay
  template-agnostic), and the fail-closed shape (an unreadable setup record
  hides the gated persona rather than advertising it).
- **±0 net** from `test_workspaces.py`: the listing-shape test
  (`test_returns_one_option_per_loaded_template`) keeps its assertion but now
  clears the gate seam explicitly, because the default deployment it runs
  against no longer offers `pm_fleet`. The real-personas test flipped from
  asserting pm_fleet is offered to asserting it is absent while
  `content_creator` is still offered — same case count, opposite pole.
  Neither case was removed.

Playwright UI coverage for the same issue (persistent-agent dock on every
page, PM-free onboarding copy, PM-Fleet-free persona picker) lives in
`hive-conductor/tests/e2e/workspace-agent-dock.spec.ts`, which is not a
pytest suite and so contributes nothing here.
