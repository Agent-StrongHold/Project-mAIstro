---
inventory-delta:
  packages/maistro-core/tests: +8
---

Issue #1090 adds tests for reserving one canonical child Run before transport,
attaching receipts idempotently, reusing the same delegation key on retry, and
persisting the single transport-boundary claim across SQLite store instances,
including the cross-replica compare-and-set race. The guest-peer recovery case
uses two real `GuestPeerManager` instances and a transport boundary, so it
exercises remote receipt reconciliation rather than replacing either method
with a test double.
