---
inventory-delta:
  packages/maistro-core/tests: +7
---
# claude-m1-462-recovery-events

**`tests/runs/test_recovery_events.py` (+7)** — the applied disposition
reaches the canonical Event stream (#462, ADR-082826-08f0 AC-7):

- a recovered cancellation says `recovered_and_parked`, because a parked
  NodeRun is otherwise indistinguishable from a paused one;
- a requested cancellation says `terminalized`, because the two meanings of a
  CANCELLED Attempt reach opposite rows of the table and an event that could
  not tell them apart would be useless;
- the Run, NodeRun and Attempt ids in the payload resolve back on the spine,
  which is the other half of the criterion — inspectable through the same Run
  model, not through a parallel record;
- replaying a completed Attempt is announced as `accepted`, not as a recovery,
  because it is the same seam and a different thing;
- a reconciler with no sink still reconciles — an unobservable recovery is the
  gap this closes, and one that refused to run because nothing was listening
  would be a worse one;
- a failed Attempt parks and says it parked, because reporting it as recovered
  would claim a process died when the work simply did not succeed;
- the lease sweep announces what it reclaimed, which is the producer path #462
  names and the one that had no record of its own decisions at all.
