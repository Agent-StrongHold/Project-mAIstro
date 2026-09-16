---
inventory-delta:
  packages/maistro-core/tests: +0
---
# Workspace lifecycle guard

The existing workspace lifecycle conformance test now constructs an independent durable
Project store after a failed Workspace purge and verifies that it cannot read
the deleting Root or create a child Project. This strengthens existing node IDs
rather than adding tests. The test runs for SQLite and
PostgreSQL when their durable legs are available; the in-memory reference is
skipped because it has no restart journal.

The implementation evidence is the database-backed lifecycle lookup in both
durable Project stores. Admission is no longer dependent on a callback attached
only to the Workspace store's Project-store instance, so a separately
constructed store observes `deleting` as well.
