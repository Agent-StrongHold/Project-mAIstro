---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue 1246 DAG-run scope pagination

Adds two collected regression cases proving that DAG-run reads remain scoped
through pagination and live SSE: a newer foreign run cannot consume the caller's
only list slot, and a stream admitted before Workspace membership revocation
cannot deliver later events.
