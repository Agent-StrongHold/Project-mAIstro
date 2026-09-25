---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Issue 1058 SQLite authorization transaction regression

Adds SQLite-specific and shared-authority regressions proving that durable
settlement holds its serialized write transaction while resolving live
Workspace membership, and waits for an in-progress membership revocation
before checking authorization. A competing writer is locked during the
SQLite authorization callback, while a revoked member is refused without
settling the pause.
