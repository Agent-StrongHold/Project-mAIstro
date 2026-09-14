---
inventory-delta:
  packages/maistro-core/tests: +5
---

The Sentinel integrity tests add coverage for Ed25519 signatures over the
complete decision payload, mutation rejection for payload/identity/timestamp/
policy snapshot, key rotation history, the authorize product path, and a
SQLite audit round-trip that preserves only public verification material.
