---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Issue 338 chat admission compensation

Adds coverage for post-commit admission transition failures at both the `CREATED -> QUEUED` and `QUEUED -> RUNNING` hops. The tests assert that uncertain writes are compensated to terminal `CANCELLED` with the sanitized `admission_incomplete` cause and that no non-terminal Run remains.
