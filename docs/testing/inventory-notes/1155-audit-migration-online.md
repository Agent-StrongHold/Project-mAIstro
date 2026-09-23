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
"Multiple head revisions are present". The revision was re-parented onto 039 and
re-parented again onto the develop chain tip 040 after merging develop restored a
039 fork (`040_capability_binding_authority` also revises 039), again making
036_audit_log_org_scope the single head. Proven on a fresh PostgreSQL 18
(pgvector) database: `upgrade head` runs the whole chain through 040 ->
036_audit_log_org_scope, the backfill normalizes pre-existing NULL-scope rows to
'', downgrade drops the column and index, and re-upgrade restores them.
