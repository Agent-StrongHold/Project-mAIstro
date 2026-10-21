---
inventory-delta:
  packages/maistro-core/tests: +96
---

# #1151 / #1098: recovery inspection measurement

`packages/maistro-core/tests/runs/test_recovery_inspection_budget.py` calls the
production `Container.recover_abandoned_attempts(limit=1)` with unchanged
accepted prefixes of 0/1/2/10 pages before a repairable completion. Each page
contains one RUNNING Run. NodeRun width (1/3) and Attempt depth (1/4) vary
independently. Normal and forced peer-first reconciliation run on the shared
memory/SQLite/PostgreSQL spine fixtures: 4 × 2 × 2 × 2 × 3 = 96 nodes.

Instrumentation delegates to real store list/get methods and counts calls and
returned records, including reads nested in the production reconciler. It does
not copy the scan algorithm or count only the outer page. Measurements are
emitted as `INSPECTION_MEASUREMENT` JSON with `pytest -s`.

Assertions distinguish inspected records from actual progress: one first-tick
repair, zero repeated/fresh-Container repairs, full unchanged prefix and physical
history, no new Attempt/NodeRun/Invocation, historical terminal exclusion,
keyset traversal, and equal repeated/fresh-Container read counts. A peer commits
via the real reconciler between before-read and own reconciliation; observation
of its progress still counts once. No sleeps or extra tick to obtain progress.

This is characterization, not a new numerical scan-work ceiling or fairness
policy. SQL rows/pages examined internally, aggregate/reclaim query costs,
Graph continuation scans, OS process death and independent-pool restart are
outside this measurement. The fresh Container uses the same store and proves
only loss of local scan state. PostgreSQL legs skip when no DSN is configured;
local execution and measured growth are recorded in the follow-up report.
