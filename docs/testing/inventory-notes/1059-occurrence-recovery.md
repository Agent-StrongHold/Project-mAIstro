---
inventory-delta:
  packages/maistro-core/tests: +7
---

Adds coverage for resolving a duplicate schedule occurrence to its canonical Run and reconciling the schedule cursor linkage after a simulated crash before `record_fire()`.
