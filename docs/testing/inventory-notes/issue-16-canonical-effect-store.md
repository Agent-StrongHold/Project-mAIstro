---
inventory-delta:
  packages/maistro-core/tests: +2
---
# issue-16-canonical-effect-store

Two tests prove the governed capability-effect composition consumes the selected
SQLite `EventStore` and preserves the explicit in-memory fallback only when no
durable backend is configured. The SQLite test appends and reads a canonical
event through the injected store, proving the context is not retaining a private
in-memory event authority. The Hive recovery seam now uses the same selected
store through `CanonicalEventStoreSink`; its existing recovery tests assert that
it no longer passes the process-local compatibility bus.
