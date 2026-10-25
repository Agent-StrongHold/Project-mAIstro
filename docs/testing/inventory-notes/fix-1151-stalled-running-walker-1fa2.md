---
inventory-delta:
  packages/maistro-core/tests: +18
---
# fix-1151-stalled-running-walker-1fa2

Six end-to-end cases in
`tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`, each run
against the memory, SQLite and PostgreSQL continuation stores (6 x 3 = +18)
over develop's file. An earlier revision of this note recorded +30 (ten
cases); the merge reconciliation below removed four of them, so the net
delta against the baseline is +18.

They hold the #1151 windows to their contract end to end: a walker whose
recovery claim was cleared by its first frontier checkpoint and which then
died leaves a RUNNING Run the due index never lists. Three drive the real
executor into that state. Two assert the shipped due tick finishes the Run
without re-running committed nodes: the last node settled but the Run did
not, and a two-node walk that died between frontiers. The third, a walk that
died inside its second node, asserts the Run is left alone while that
Attempt's lease is live and made due once it lapses (resuming it needs the
lease lapsed in wall time, which the executor reads itself). The other three
pin the repair's shape at the store boundary: the stranded continuation is
made due with an elapsed claim (version+1) and a second tick is idempotent,
the continuation is not claimed while the spine moved within the
terminal-settle quiet period, and a recovering walker's own claim is never
reclaimed.

## Merge reconciliation (supersession)

The branch originally added a separate per-version-observation repair
(`_reconcile_stalled_walk`) for the same RUNNING/RUNNING unclaimed state.
develop's reviewed stalled-active-frontier repair (#1942, with the #1861
quiet-period protection) owns that state and runs first, which made the
branch's repair unreachable and its four remaining cases contradictory with
the landed design:

- the restarted-replica stanza (no claim on a first tick past the quiet
  period) contradicts `test_crashed_empty_frontier_walker_is_still_recovered_
  after_quiet_period`, which requires exactly that single-tick recovery;
- the lease-less stanza (an open Attempt with no lease is never presumed
  dead) contradicts the reviewed `has_live_execution_lease` stance the
  frontier repair is built on;
- the two bookkeeping cases poked `_stalled_first_seen`, an attribute of the
  removed repair.

Those four cases were removed with the unreachable repair; canonical_store.py
is byte-identical to develop's. The strict-xfail markers in
`test_canonical_durable_store.py` continue to hold (verified: 4 xfailed, none
xpass).

Each surviving guard was checked to fail when the behaviour it names is
refused: the lease-lapse case fails if the lapsed continuation is not made
due; the quiet-period case fails if the continuation is claimed before the
period elapses; the elapsed-claim case fails if the repair does not advance
the version exactly once.
The PostgreSQL leg needs `MAISTRO_TEST_PG_DSN` and runs in quality.yml's
`coverage-postgres` job.
