---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-server/tests: +0
---
# M2-A7 durable-state contract

Adds coverage for SQLite usage-event idempotency under overlapping flushes, same-timestamp events, crash/retry logical identities, SQLite elevation-grant restart/expiry semantics, and container wiring of SQLite durability layers.
