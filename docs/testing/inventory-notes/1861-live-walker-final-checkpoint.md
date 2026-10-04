---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Live-walker final-checkpoint recovery regression (#1861)

## What moved

`packages/maistro-core/tests/graph/durable_runs` gains six collected node IDs:
`test_live_walker_final_checkpoint.py` adds one named regression
(`test_live_walker_final_checkpoint_is_not_claimed_by_recovery`) and one
companion crash-oracle case
(`test_crashed_empty_frontier_walker_is_still_recovered_after_quiet_period`),
each parametrized over `memory` / `sqlite` / `postgres` backends. The
PostgreSQL parametrization runs a real `PgRunStore` plus
`PgGraphContinuationStore`, with the recovery instance on its own asyncpg pool
so the tick reads the walker's writes through an independent connection.

## Why

A live canonical walker that has committed its final empty-frontier checkpoint
but not yet written its terminal Run checkpoint presents an active frontier of
zero NodeRuns — every NodeRun is terminal, no Attempt holds a lease, the
continuation reads RUNNING with no `resume_at`. `_has_stalled_active_frontier`
fell through `True` for that state (the guard #1715 removed while inlining the
lease helper), so one recovery tick re-queued the continuation under the live
walker: `resume_at` set, version advanced, and the walker's terminal
checkpoint died on `version regression: stored=N incoming=N`. The named test
drives the real executor into exactly that barrier, holds it while a second
`CanonicalDurableRunStore` instance over the same authorities runs one
recovery tick, and asserts the tick changes nothing before releasing the
walker to complete on its original Attempt.

The empty frontier is also what a walker that *died* in the same window leaves
behind, and that residue must still be recovered. A bare
`if not active_node_runs: return False` (the pre-#1715 guard) keeps the live
walker safe but strands the dead one forever: a RUNNING continuation with no
`resume_at` is invisible to the due index, so nothing ever settles it. The
companion case pins that oracle — it fails under the bare early return (proved
against this branch) and passes under the repair, which claims the empty
frontier only once the spine has been quiet past
`TERMINAL_SETTLE_QUIET_PERIOD`, the same span past which no live walker is
assumed anywhere else in the store. Both tests count one physical node
execution and exactly one Attempt with an accepted outcome, so a duplicate
effect or a second Attempt cannot hide behind a green assertion.
