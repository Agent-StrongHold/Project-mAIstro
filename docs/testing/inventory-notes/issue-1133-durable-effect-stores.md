---
inventory-delta:
  packages/maistro-core/tests/test_container_capability_effects.py: +2
---
# Issue 1133 Durable Effect Stores

Added two integration tests covering the shipped Container effect path:

- SQLite selects durable Binding/Invocation stores and one canonical backend-selected
  EventStore, with Binding and Event persistence visible after Container restart.
- Two independent SQLite connections racing the same logical capability Invocation
  identity leave exactly one authoritative row.
