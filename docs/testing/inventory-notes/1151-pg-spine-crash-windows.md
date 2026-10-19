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
  Run through the public `Container.recover_abandoned_attempts` tick, with no
  new Attempt or Invocation and unchanged physical history;
- a Run settlement lost after its last NodeRun committed settles from the
  accepted outcome alone through that same public tick, preserving the full
  accepted NodeRun and Attempt records across first and repeated recovery;
- the RUNNING sweep pages past a 60-Run backlog in three bounded pages
  through the real `(created_at, run_id)` keyset;
- two independent pools sweeping the same residue concurrently converge on
  exactly one settlement, the continuation version unchanged (the fence),
  and both replicas' follow-up ticks are no-ops.

The Graph walker is interrupted at a commit seam on its own pool; the two
spine-only cases construct the exact committed residue through canonical
store APIs. Recovery runs the production seams (`reconcile_persistence`,
`resume_due_graph_runs`, `Container.recover_abandoned_attempts`) on a fresh
pool built by the test, so every pre-recovery assertion is an independent
committed read. Independent pools model restart; no OS process is killed.
No sleeps and no extra ticks to obtain first progress: the only clock advanced
is the tick's own `now`, past the quiet periods the production policy defines.
Follow-up ticks assert fixed points, not eventual success.

Current-round repair replaces the test-local terminal enumeration (which
counted only parent settlement, unlike production) with the real Container
entry point. Its unrelated services use memory, while every lifecycle query
and mutation goes through the independent `PgRunStore`. The existing eleven
collected nodes and this note's `+11` inventory delta are unchanged.
