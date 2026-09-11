---
inventory-delta:
  packages/hive-conductor/tests/e2e: +1
---
# Design Studio persisted project readback

Adds one browser regression for the Design Studio parent surface. It supplies a
persisted-project response from the Design service and verifies the UI renders
that durable project and stored-output fact without presenting it as visual
generation. The existing unavailable-generation and no-timer assertions remain
in the same scenario.
