---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Issue 12 Durable Persona Store

The live Workspace Persona now has a SQLite durable implementation and a
PostgreSQL migration/store twin. These tests prove the one-Persona-per-Workspace invariant, restart recovery,
detached update snapshots, and cascade cleanup when the owning Workspace is
deleted in both durable and in-memory ownership wiring.
