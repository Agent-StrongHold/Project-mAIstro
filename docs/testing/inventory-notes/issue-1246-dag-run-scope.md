---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# Issue 1246 DAG-run scope pagination

Adds one collected regression case proving that DAG-run list pagination is
applied after canonical Workspace authorization: a newer foreign run cannot
consume the caller's only list slot or hide an older in-scope run.
