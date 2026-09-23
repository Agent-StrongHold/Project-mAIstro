---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---
# claude-ws-37-implement-the-owner-decision-shared-post-06f4

Adds `packages/hive-conductor/backend/tests/test_workspace_authority_durable.py`
(#37, ADR-092326-97c4): ten node IDs in all. Three tests boot the real
`MaistroCoreBridge` against a real database and restart it. Each runs once on
SQLite and once on PostgreSQL, for six node IDs; the PostgreSQL copies skip
without `MAISTRO_TEST_PG_DSN`. They cover durable-store selection,
revocation/deletion surviving restart with no mirror writes, and a one-time
legacy mirror import that never resurrects deleted rows. The other four
cover the fail-closed refusal when a configured database has no Container,
the unchanged no-database fallback, a pathless `sqlite://` URL (in-memory, so
the mirror stays recovery evidence), and the compose wiring.

In `test_workspace_authority.py`, the durable-retirement test was renamed in
place for the new contract, which leaves the mirror untouched. That rename
changes no count.
