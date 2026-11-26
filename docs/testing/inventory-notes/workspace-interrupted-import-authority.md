---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# Interrupted durable Workspace import preserves canonical authority

Three cases, each parametrized over SQLite and PostgreSQL, cover canonical
revocation and deletion after an injected failure at the final Hive journal
write, plus an interrupted marker before canonical creation. Restart must not
replay identity or roster; source and journal remain intact, quarantine is
visible to the existing inspection seam, and unrelated fresh imports proceed.

The three SQLite cases fail against the original implementation. PostgreSQL
cases are mandatory in CI's existing supported-major migration jobs; an absent
DSN fails there rather than silently skipping. No claim is made here that a
missing local journal proves initial migration, or that the first import's
cross-process roster writes are atomic. Those #37/#1419 tails remain open.
