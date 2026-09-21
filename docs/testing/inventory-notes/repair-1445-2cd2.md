---
inventory-delta:
  packages/maistro-core/tests: +3
---
# repair-1445-2cd2

+3 in packages/maistro-core/tests/persistence/test_pg_learnings.py: store-level
tests for `PgLearningStore.find_similar` — the EMBEDDING_DIMENSIONS guard
(refuses before any SQL runs), the `hnsw.iterative_scan` SET LOCAL pragma
running inside the same transaction as the fetch, full scope-axis binding
(org/team/user/agent + LIMIT) and the omitted-axes case where org_id stays
bound so an unscoped read stays a global read, never a wildcard. Completes
the #1156 learning scope/provenance lane's coverage of the pg backend.
