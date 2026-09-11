---
inventory-delta:
  packages/maistro-core/tests: +9
---

# Workspace lifecycle crash recovery (#1121)

Adds three durable Workspace lifecycle cases covering restart completion after
creation staging, deletion failure before Project purge, and deletion failure
after Project purge. The suite inventory delta is +9 against the repository
baseline: three node IDs come from this change and six were already present as
unrecorded develop-head drift. The tests exercise the SQLite implementation
directly and the PostgreSQL leg when `MAISTRO_TEST_PG_DSN` is configured; the
in-memory reference is intentionally skipped because it has no restart
boundary.
