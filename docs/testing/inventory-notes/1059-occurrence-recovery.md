---
inventory-delta:
  packages/maistro-core/tests: +8
---

Adds coverage for resolving a duplicate schedule occurrence to its canonical Run and reconciling the schedule cursor linkage after a simulated crash before `record_fire()`. Also covers the torn-state path where a duplicate claim's winner cannot be resolved through the occurrence index: the batch stops with a `RunIntegrityError` recorded and the cursor unmoved.
