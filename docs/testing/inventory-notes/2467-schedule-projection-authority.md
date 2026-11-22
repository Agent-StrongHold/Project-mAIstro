---
inventory-delta:
  packages/hive-conductor/backend/tests: +22
---

# Startup reconciliation converges the schedule projection on canonical truth (#2467)

`packages/hive-conductor/backend/tests/test_schedule_projection_authority.py`
is new: 22 node IDs over the in-memory store and a SQLite store on a tmp file,
behind a real `create_container` Container swapped into the engine. The SQLite
leg re-opens the store across the simulated restart, so the canonical rows
under test are the persisted ones.

The routes write the canonical `ScheduleStore` definition first and the Hive
row second, with no shared commit; startup reconciliation used to answer every
crash window by re-putting a Hive-row-derived definition whenever canonical was
missing or drifted — the projection overruling the authority. The new tests
hold the replacement policy: a restart that finds the projection behind an
acknowledged disable, rename, or recurrence edit repairs the projection and
never the definition (cursor-preserving, with the substrate's own
recurrence-clears-due-cursor contract); a deleted schedule stays deleted under
its durable tombstone, and a tombstone-less stale row is degraded and never
reimported; an interrupted create resolves to one visible identity through its
durable pending marker, or closes as never-committed; legacy import happens
exactly once, bounded by the migration marker; recorded cursors, Run ids, and
due state survive repeated and concurrent (two-replica) reconciliation
unchanged; a post-marker startup never runs the import pass for a
canonicalized id; and the fire path reads the definition it spends from
canonical truth, so a stale projection cannot hand an exhausted schedule fresh
quota. `scheduler_status` reports the reconciliation outcome and degraded rows
(#290). Two existing tests were updated, not removed: the runner-startup
orchestration patch targets `reconcile_schedule_projection`, and the
`_definition_for` contract test asserts the new read-first authority (stored
definition stands; first put still belongs to a never-canonicalized row).
