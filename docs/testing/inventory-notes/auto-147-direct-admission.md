---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 147 direct admission wiring

Adds regression coverage proving directly admitted work names the reserved system
A2A principal instead of an empty `from_agent`, and that the production agent
factory grants that principal only the loaded roster's targets.
