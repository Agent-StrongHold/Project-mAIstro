---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# auto-465-1ef5

The Design render-facade repair adds one collected backend node: the regression
covering an owned project returning 501 without creating an unadvancable pending
job. Keep this delta separate from the original #465 note because the inventory
ledger counts each worktree change independently.
