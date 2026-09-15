---
inventory-delta:
  tests/: +3
---
# 1155 audit migration online

Adds three migration-conformance tests for revision 036: the real Alembic
chain reaches the audit migration, the legacy scope backfill is bounded into
repeated batches, and upgrade/downgrade build and drop the scope index through
PostgreSQL autocommit-concurrent operations.
