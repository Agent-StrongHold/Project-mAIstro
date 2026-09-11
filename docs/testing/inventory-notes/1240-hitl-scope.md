---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Issue 1240 — HITL workspace scoping

Adds one HTTP regression case covering listing, answering, and cancelling: a
principal with `dags.write` can only reach pauses in its canonical Workspace
membership set.
