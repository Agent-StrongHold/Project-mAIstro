---
inventory-delta:
  packages/maistro-core/tests: +8
---
# Issue 338 chat admission compensation

Adds coverage for post-commit admission transition failures at both the `CREATED -> QUEUED` and `QUEUED -> RUNNING` hops, plus a recovery tick retry after the compensating write itself fails. The tests also prove a live admission receipt wins a recovery race, an expired receipt is recovered, and pagination reaches an expired receipt behind 100 live rows. The tests assert that uncertain writes are compensated to terminal `CANCELLED` with the sanitized `admission_incomplete` cause and that no unowned non-terminal Run remains. The added cross-container cases prove durable receipt renewal protects a slow owner and recovery later disposes of an actually expired receipt.
