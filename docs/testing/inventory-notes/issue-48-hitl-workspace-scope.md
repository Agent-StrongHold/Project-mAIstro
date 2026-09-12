---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +2
---
# issue-48-hitl-workspace-scope

Adds an end-to-end HITL authorization regression covering the pending queue and
answer/cancel mutations across canonical Workspace boundaries. The test proves
a principal sees only paused Runs in Workspaces where it is a member and cannot
settle another tenant's human pause.
