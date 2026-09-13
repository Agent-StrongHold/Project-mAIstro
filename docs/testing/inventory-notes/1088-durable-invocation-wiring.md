---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Durable capability invocation wiring

The reachability contract test suite replaced three stale assertions that
claimed the capability Invocation store was intentionally unwired and had no
migration. The replacement assertions now prove the live container selects durable
SQLite capability and event stores and migration `034_capability_invocations.py`
exists. A PostgreSQL round-trip test was added in the same suite, for a net
collection increase of two nodes.
