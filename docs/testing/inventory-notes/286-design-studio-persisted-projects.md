---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/hive-conductor/tests/e2e: +2
---
# Design Studio persisted project readback

Adds browser regressions for the Design Studio parent surface: one supplies a
persisted-project response and verifies that durable project/output facts render
without presenting them as visual generation, while the other verifies that a
503 persistence response is shown as unavailable rather than as an empty
project list. Backend route tests cover both disabled and uninitialized stores for project
listing/rendering and prove the in-scope render facade fails with 501 rather
than creating a pending job; the existing unavailable-generation and no-timer
assertions remain in the same scenario.
