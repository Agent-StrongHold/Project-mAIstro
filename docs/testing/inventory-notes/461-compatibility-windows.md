---
inventory-delta:
  packages/maistro-core/tests: +3
---

# Compatibility-window fitness test delta (#461)

Issue #461 adds `packages/maistro-core/tests/fitness/test_compatibility_windows.py` with three architecture-fitness tests: the trusted-base + durable-evidence registry check (canonical-surface pins, alias record shape, trusted-base removal requiring an explicit disposition), the persisted-migration fixture/loader evidence check, and the trusted-base field-removal disposition check. The suite now collects 9367 node IDs against an expected 9364 (baseline 7690 + recorded deltas 1674), recorded here as +3 rather than regenerating a shared absolute.
