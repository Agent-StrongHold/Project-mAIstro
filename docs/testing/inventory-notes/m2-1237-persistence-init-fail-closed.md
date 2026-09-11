---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# m2-1237 — persistence initialization must fail closed

Issue #1237 replaces the Foundation state fallback with a startup failure and
removes the lifespan fallback that rebound security-critical stores to memory.

- `packages/hive-conductor/backend/tests/test_foundation.py` (+2): the new
  lifespan regression proves a Foundation state failure propagates and never
  calls `stores.initialize_stores()`. The strengthened state-failure test proves
  the boundary does not publish an empty user registry and that cleanup
  failures are logged while the original persistence error remains the startup
  failure; a constructor-failure case covers the no-state cleanup branch.
