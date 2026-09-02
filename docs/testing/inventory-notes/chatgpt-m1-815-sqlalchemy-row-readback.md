---
inventory-delta:
  packages/maistro-design/tests: +3
  packages/maistro-core/tests: +1
---
# Issue #815 SQLAlchemy row readback inventory

Adds three Design-package test nodes covering real SQLAlchemy Row reads through `get`, `list_by_skill`, and `list_by_org`. Adds one cross-package persistence integration test under `packages/maistro-core/tests/persistence`, which the existing PostgreSQL 17/18 CI jobs execute after migrations, proving create-to-readback for a persisted Design output and its execution provenance on the shipped database profile.
