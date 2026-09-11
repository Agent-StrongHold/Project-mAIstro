---
inventory-delta:
  packages/maistro-core/tests/graph/nodes: +2
---

Issue #1090 adds tests for reserving one canonical child Run before transport,
attaching receipts idempotently, and reusing the same delegation key on retry.
