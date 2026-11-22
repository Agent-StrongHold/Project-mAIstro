---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# #1036: consistent batch inspection for colliding projection IDs

Two cases use a real RunExecutionService and scoped InMemoryRunStore to establish
canonical visibility, then add a same-ID projection in a foreign Workspace or
without Workspace scope. Detail, stream admission and batch visibility must all
refuse that existing projection under the current inspection policy.

Both cases fail against develop 35a72ff54d4f09429cf0b9349ecff7f3e9396f5d:
batch visibility includes the ID while detail and stream admission refuse it.
The fix limits canonical batch fallback to genuinely absent projection rows.
This is policy-consistency evidence, not proof of unauthorized canonical-data
disclosure, canonical PostgreSQL recovery, or a historical coexistence decision.
The separate #2175 projection-writer correction is unaffected.
