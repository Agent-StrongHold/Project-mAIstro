---
inventory-delta:
  packages/maistro-core/tests: +54
---
# 1151 — cross-store crash reconciliation

Adds `packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`:
eighteen behavioural tests, each parametrized over the memory, SQLite and PostgreSQL
continuation backends (18 × 3 = +54 node IDs; the PostgreSQL rows skip without
`MAISTRO_TEST_PG_DSN`). They drive the real executor into the crash window
between the Graph continuation write and the canonical spine mirror
(COMPLETED, FAILED with a lost error, FAILED whose mirrored NodeRun error is
not passed off as the Run's lost cause,
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

Codex review of the ready PR added three more. A terminal write newer than an
already-quiet spine is held until the same continuation version has been
observed for the whole quiet period, and a new version restarts that
observation. A resume claim that has elapsed in the due tick's own `now` is
reconciled and resumed by that tick, because reconciliation now judges it at
the tick's evaluation time rather than the wall clock.
