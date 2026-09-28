---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +1
---

# #72 pathless SQLite usage-log health disposition

`test_persistence_diagnostics_reports_pathless_write_behind_as_ephemeral`
extends the durable-state health contract: a configured `SqliteUsageLog`
write-behind layer over a pathless `sqlite://` container remains
restart-ephemeral. The test protects against the diagnostics layer overwriting
the actual in-memory backend disposition merely because a persistence object is
wired. The existing container-wiring test additionally asserts that the actual
pathless `sqlite://` profile records `stores_memory_backed=True` for the health
surface to consume.
