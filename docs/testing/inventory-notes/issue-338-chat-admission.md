---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Issue 338 chat admission compensation

Adds coverage for post-commit admission transition failures at both the `CREATED -> QUEUED` and `QUEUED -> RUNNING` hops, plus a recovery tick retry after the compensating write itself fails. The tests assert that uncertain writes are compensated to terminal `CANCELLED` with the sanitized `admission_incomplete` cause and that no unowned non-terminal Run remains.
