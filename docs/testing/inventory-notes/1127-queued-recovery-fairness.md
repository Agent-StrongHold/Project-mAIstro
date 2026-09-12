---
inventory-delta:
  packages/maistro-core/tests: +4
---
# #1127 queued Graph recovery fairness

Adds one recovery regression proving owned queued work is found behind a
foreign prefix, and one parametrized RunStore conformance case (four collected
node IDs including the three backend legs) proving the durable admission source
filter behaves consistently for in-memory, SQLite, and PostgreSQL stores.
