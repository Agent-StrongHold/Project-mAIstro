---
inventory-delta:
  packages/maistro-core/tests: +7
---

Issue #1090 adds tests for reserving one canonical child Run before transport,
attaching receipts idempotently, reusing the same delegation key on retry, and
persisting the single transport-boundary claim across SQLite store instances.
