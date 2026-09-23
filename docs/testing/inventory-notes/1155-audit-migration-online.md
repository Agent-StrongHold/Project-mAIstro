---
inventory-delta:
  tests/: +3
---
# 1155 audit migration online

Adds three migration-conformance tests for revision 036: the real Alembic
chain reaches the audit migration, the legacy scope backfill is bounded into
repeated batches, and upgrade/downgrade build and drop the scope index through
PostgreSQL autocommit-concurrent operations.

Repair (2026-09-23): the revision initially parented on 035_outcome_scope_thumb_index
and then on 038, both of which already had children on develop — each choice left
the chain with two heads, so ordinary `alembic upgrade head` failed with
"Multiple head revisions are present". The revision now follows the chain tip
039, making 036_audit_log_org_scope the single head. Proven on a fresh
PostgreSQL 18 (pgvector) database: `upgrade head` runs the whole chain through
039 -> 036_audit_log_org_scope, the backfill normalizes pre-existing NULL-scope
rows to '', downgrade to 039 drops the column and index, and re-upgrade restores
them.
