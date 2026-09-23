---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# 1248-registration-identity-concurrency

**+1 `packages/hive-conductor/backend/tests`** — concurrent open registration
requests with the same username are forced to overlap after the availability
check. The real synchronous route must return one success and seven conflicts,
with exactly one stored identity, covering the UUID-keyed check-then-write race.
