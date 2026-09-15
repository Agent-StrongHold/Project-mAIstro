---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/hive-conductor/backend/tests: +2
---

# #846 live capability admission

Adds behavioral coverage for Binding revocation, shipped harness-route revocation,
and self-repair policy-provider failure. The tests assert that an already-built
actor performs no provider call after capability/binding withdrawal and that a
policy failure produces a failed/degraded repair rather than granting the effect.
