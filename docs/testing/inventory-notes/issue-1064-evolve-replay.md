---
inventory-delta:
  packages/maistro-evolve/tests: +2
  packages/hive-conductor/backend/tests: +2
---

Adds issue #1064 coverage for logical tournament publication identity across a
state-file reopen, finalization replay without duplicate lineage/cycle advance,
and restart reconstruction of Evolve collaborators from durable Run references.
