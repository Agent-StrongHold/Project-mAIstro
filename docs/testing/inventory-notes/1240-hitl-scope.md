---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# Issue 1240 — HITL workspace scoping

Adds three HTTP regression cases: a principal without `dags.write` cannot
answer or list, and a principal with `dags.write` can only list, answer, or
cancel pauses in its canonical Workspace membership set.
