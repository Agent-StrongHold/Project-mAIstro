---
inventory-delta:
  packages/maistro-core/tests: +11
---

# 1151 R7: real-PG spine crash windows over both durable authorities

`tests/runs/test_pg_spine_crash_windows.py` delivers the R7 bounded proof
artifact from the issue: crash-window proofs on actual `PgRunStore` and
`PgGraphContinuationStore`, not the in-memory spine
(`test_crash_window_invariants.py`) or the PostgreSQL-continuation /
InMemoryRunStore pairing (`test_cross_store_crash_reconciliation.py[postgres]`)
that cannot prove both authorities durable.

Eleven tests, all skipped unless `MAISTRO_TEST_PG_DSN` names a migrated
database:

- a stale RUNNING continuation under a canonically terminal COMPLETED or FAILED
  Run is repaired from the authoritative spine by a fresh pool, then remains a
  no-op on the next tick;
- a FAILED continuation whose canonical mirror was lost settles on the first
  eligible tick (past the terminal-settle quiet period), with the open
  NodeRun cancelled by the spine's own cascade;
- a COMPLETED continuation whose NodeRun mirrors committed settles once the
  restarted replica has observed the terminal version for the quiet period,
  re-deriving the result from persisted NodeRun evidence;
- the QUEUED-continuation / RUNNING-Run checkpoint-1 window is made visible to
  the due index by the sweep and resumed to COMPLETED by the due tick;
- a live (not yet elapsed) claim is left to its walker: no repair, no resume;
- a frontier NodeRun minted without its checkpoint (`resume_at=None`, no
  Attempt holding it) is made due by the stalled-frontier repair and walked
  to completion by the due tick;
- an Attempt completion committed before reconciliation settles NodeRun and
  Run through `AttemptLifecycleReconciler`, with no new Attempt;
- a Run settlement lost after its last NodeRun committed settles from the
  accepted outcome alone;
- the RUNNING sweep pages past a 60-Run backlog in three bounded pages
  through the real `(created_at, run_id)` keyset;
- two independent pools sweeping the same residue concurrently converge on
  exactly one settlement, the continuation version unchanged (the fence),
  and both replicas' follow-up ticks are no-ops.

The walker writes and dies at one exact commit seam on its own pool; recovery
runs the production seams (`reconcile_persistence`, `resume_due_graph_runs`,
`AttemptLifecycleReconciler` over the bounded `list_by_status` enumeration) on
a fresh pool built by the test, so every pre-recovery assertion is an
independent committed read. No sleeps and no extra ticks: the only clock
advanced is the tick's own `now`, past the quiet periods the production
policy defines.
