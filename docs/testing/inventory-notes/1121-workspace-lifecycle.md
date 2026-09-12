---
inventory-delta:
  packages/maistro-core/tests: +21
---

# Workspace lifecycle crash recovery (#1121)

Adds seven durable Workspace lifecycle cases covering restart completion after
creation staging, active-orphan rollback, failed compensation recovery, SQLite
write rollback, deletion quarantine, deletion failure before Project purge, and
deletion failure after Project purge. The suite inventory delta is +21 against
the repository baseline: seven parameterized cases contribute twenty-one node
IDs and six were already present as unrecorded develop-head drift. The tests
exercise the SQLite implementation
directly and the PostgreSQL leg when `MAISTRO_TEST_PG_DSN` is configured; the
in-memory reference is intentionally skipped because it has no restart
boundary.
