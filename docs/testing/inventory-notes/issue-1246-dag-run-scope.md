---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# Issue 1246 DAG-run scope pagination

Adds five collected regression cases proving that DAG-run reads remain scoped
through pagination and live SSE: a newer foreign run cannot consume the caller's
only list slot; a stream cannot deliver an event after membership revocation;
and idle streams honor keepalive, disconnect, and revocation checks.
