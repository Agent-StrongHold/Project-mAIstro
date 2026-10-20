---
inventory-delta:
  packages/maistro-core/tests: +15
---

Adds coverage for resolving a duplicate schedule occurrence to its canonical Run and reconciling the schedule cursor linkage after a simulated crash before `record_fire()`. Also covers the torn-state path where a duplicate claim's winner cannot be resolved through the occurrence index: the batch stops with a `RunIntegrityError` recorded and the cursor unmoved.

Follow-up repair (#1269 findings) adds seven node IDs: the occurrence-ordering guard on `_advance` is exercised across all three store backends (an older occurrence cannot regress the stored link/due pair); a transient failure of the duplicate-winner lookup is recorded as a batch-stopping failure while occurrences admitted earlier in the batch still reach `record_fire`; and a Run carrying an occurrence claim is excluded from the archive sweep on the in-memory reference store and on both archive-tier backends, where the claim must survive a sweep with its winner still resolvable and its occurrence still owned.
