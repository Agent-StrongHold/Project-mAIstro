---
inventory-delta:
  tests/: +2
---
# 1155 audit migration online

Adds two migration-conformance tests for revision 035: the legacy scope
backfill is bounded into repeated batches, and upgrade/downgrade build and drop
the scope index through PostgreSQL autocommit-concurrent operations.
