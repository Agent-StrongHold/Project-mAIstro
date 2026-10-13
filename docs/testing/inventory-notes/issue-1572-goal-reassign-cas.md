---
inventory-delta:
  packages/maistro-core/tests: +9
---
---
# Issue #1572 Goal reassignment compare-and-set repair

Round 98 of the #1572 lane: the durable Goal stores' guarded UPDATEs guarded
only `current_revision` and `status`, but a reassignment moves neither — and
every mutation writes the whole-row payload from its read. Two concurrent
`reassign_agent` calls on PostgreSQL both landed, the second recording a
`from_agent_id` the row no longer held; an append or transition whose read
predated a landed reassignment wrote the stale owner back through the payload.

The fix carries the owner as read in all three guarded UPDATEs
(`pg_store.py`, `sqlite_store.py`), so zero rows has one meaning: the Goal
moved between the read and the write.

Three conformance tests added to
`packages/maistro-core/tests/goals/test_goal_store_conformance.py`, each
parametrized over memory/sqlite/postgres (+9 collected nodes; the two
held-read legs skip on the reference, whose lock makes the read/write window
structurally unable to open):

- `test_concurrent_reassignments_record_truthful_ownership` — the audit
  chain each store records ends exactly at the row's owner; every loser gets
  the one `GoalRevisionConflict`.
- `test_a_reassignment_that_read_before_another_writer_landed_is_refused` —
  deterministic race (read held open while a complete out-of-band
  reassignment commits): refused, nothing recorded, a fresh read re-derives
  and records the true prior owner.
- `test_an_append_that_read_before_a_reassignment_landed_is_refused` — the
  stale-payload clobber: refused, the landed reassignment survives.

Both durable failures reproduced first against the pre-fix stores
(`332c24c54` stores + these tests: 5 failed — the PG audit lie, both
stale-writer legs, on sqlite and postgres) and pass with the fix.
