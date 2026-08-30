---
inventory-delta:
  packages/maistro-core/tests: +2
---

# M1 #61 event sequence durability evidence

This change adds two maistro-core regression tests proving that the canonical Workspace event sequence continues across a store restart and remains serialized across independent SQLite connections/store instances.
