---
inventory-delta:
  packages/maistro-core/tests: +27
---
# 1151 — cross-store crash reconciliation

Adds `packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`:
nine behavioural tests, each parametrized over the memory, SQLite and PostgreSQL
continuation backends (9 × 3 = +27 node IDs; the PostgreSQL rows skip without
`MAISTRO_TEST_PG_DSN`). They drive the real executor into the crash window
between the Graph continuation write and the canonical spine mirror
(COMPLETED, FAILED with a lost error, FAILED with a mirrored NodeRun error,
non-HITL CANCELLED, a lost race to the same repair), the QUEUED-continuation /
RUNNING-Run resume-claim window (elapsed and live claims, with and without an
explicit reconcile before the due tick), and a stranded Run behind 150 other
RUNNING Runs and 150 QUEUED continuations. No test was removed or moved.
