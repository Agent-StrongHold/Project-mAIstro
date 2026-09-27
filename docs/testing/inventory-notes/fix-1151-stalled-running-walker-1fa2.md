---
inventory-delta:
  packages/maistro-core/tests: +24
---
# fix-1151-stalled-running-walker-1fa2

Eight new cases in
`tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`, each run
against the memory, SQLite and PostgreSQL continuation stores (8 x 3 = +24).
Nothing was removed or renamed.

They cover the #1151 windows #1554 left open: a walker whose recovery claim
was cleared by its first frontier checkpoint, and which then died, left a
RUNNING Run the due index never lists. Three drive the real executor into
that state. Two assert the shipped due tick finishes the Run without
re-running committed nodes: the last node settled but the Run did not, and a
two-node walk that died between frontiers. The third, a walk that died inside
its second node, asserts the Run is left alone while that Attempt's lease is
live and made due once it lapses (resuming it needs the lease lapsed in wall
time, which the executor reads itself). Five pin what keeps
the repair off a Run a walker might still hold: the repair's own shape and
idempotence, the per-version observation period, the quiet-spine check, a
live recovery claim, and an open Attempt with no lease (never presumed dead).

Each guard was removed in turn to confirm the case that names it fails.
The PostgreSQL leg needs `MAISTRO_TEST_PG_DSN` and runs in quality.yml's
`coverage-postgres` job.
