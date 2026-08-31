---
inventory-delta:
  packages/maistro-design/tests: +4
---
# Issue #815 SQLAlchemy row readback inventory

Adds four test nodes covering real SQLAlchemy Row reads through `get`, `list_by_skill`, and `list_by_org`, plus a migrated-PostgreSQL create-to-readback round trip for persisted Design output and execution provenance.
