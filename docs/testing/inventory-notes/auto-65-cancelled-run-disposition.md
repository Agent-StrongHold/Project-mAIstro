---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# Issue 65 — distinguish cancelled execution evidence

Adds a regression asserting a cancelled Run is represented with a distinct
execution disposition, while an active Run remains the more actionable
combined disposition. This does not change canonical Run lifecycle or Goal
state authority.
