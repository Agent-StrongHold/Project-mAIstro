---
inventory-delta:
  packages/maistro-core/tests: +45
---
# 1151 — cross-store crash reconciliation

Adds `packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`:
fifteen behavioural tests, each parametrized over the memory, SQLite and PostgreSQL
continuation backends (15 × 3 = +45 node IDs; the PostgreSQL rows skip without
`MAISTRO_TEST_PG_DSN`). They drive the real executor into the crash window
between the Graph continuation write and the canonical spine mirror
(COMPLETED, FAILED with a lost error, FAILED with a mirrored NodeRun error,
non-HITL CANCELLED, a lost race to the same repair), the QUEUED-continuation /
RUNNING-Run resume-claim window (elapsed and live claims, with and without an
explicit reconcile before the due tick), and a stranded Run behind 150 other
RUNNING Runs and 150 QUEUED continuations. Three more pin the guards: a
fresh terminal write is left to its walker for the quiet period, a refused
repair is logged without stopping the rest of the tick, and a WAITING Run
under a COMPLETED continuation is skipped rather than raising. No test was
removed or moved. The last three cover a claim another writer advanced first,
a HITL-evidenced cancellation left to the HITL repair, and the RUNNING sweep
not spending the per-status budget.
