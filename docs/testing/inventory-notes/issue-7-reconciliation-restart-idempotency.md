---
inventory-delta:
  packages/maistro-core/tests: +1
---

Adds `test_replayed_physical_admission_returns_the_existing_run` to the Goal reconciliation production suite. It asserts repeated fulfilment of one durable decision key returns one Run id and leaves exactly one corresponding canonical Run.
