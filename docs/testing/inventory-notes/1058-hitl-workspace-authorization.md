---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Issue 1058 - HITL Workspace authorization

Adds an end-to-end timeout-route regression case proving a principal with
`dags.write` can settle an expired pause only in a canonical Workspace where
the principal is a member; a foreign Workspace remains paused.
