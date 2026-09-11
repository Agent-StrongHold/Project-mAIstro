---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-147 repair

Adds a factory-level regression proving the production agent roster projects
its delegation allow-list into the Container-owned A2A delegator. The Hive
composition test also asserts that the same delegator is passed to the factory.
