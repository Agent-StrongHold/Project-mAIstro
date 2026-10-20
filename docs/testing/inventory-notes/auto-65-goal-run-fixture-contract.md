---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
---
# Issue #65 — align Goal/Run browser fixtures with the production projection

Corrected existing Playwright fixtures in
`packages/hive-conductor/tests/e2e/goal-run-roundtrip.spec.ts`: a Goal with a
failed child Run now reports the production `blocked` disposition and failure
blocker; a paused human-waiting Run reports `waiting_human` without a failure
blocker. These are fixture corrections, not new tests. The Playwright suite is not part
of the pytest-collected inventory; the registered Conductor backend suite has
no count delta.
