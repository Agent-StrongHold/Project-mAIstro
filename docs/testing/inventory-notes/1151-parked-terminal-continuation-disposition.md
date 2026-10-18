---
inventory-delta:
  packages/maistro-core/tests: +15
---

# 1151 parent-held characterization: parked canonical x terminal continuation rows

`tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`
delivers the parent-held parked-conflict characterization from #1151's dispatch
scope: the four reachable `WAITING/PAUSED x COMPLETED/FAILED` rows, their
pending-decision/HITL evidence, and a second repairable Run proving isolation.

The accepted disposition table keeps these rows preserved: a parked Run awaits
its existing retry/answer decision, terminal history is not rewritten, and no
lifecycle edge is invented from WAITING/PAUSED to a terminal status. Repair of
the rows is DESIGN_BLOCKED by that same table — this artifact characterizes the
rows and the sweep's refusal behavior; it does not add a repair branch and does
not invert the intentional zero-repair behavior of
`test_a_waiting_run_under_a_completed_continuation_does_not_abort_the_tick`
(`test_cross_store_crash_reconciliation.py`), which stays in force for the
WAITING-under-COMPLETED row this file now covers alongside its three siblings.

Fifteen nodes: a 2x2 matrix (parked canonical WAITING/PAUSED x terminal
continuation COMPLETED/FAILED) over three store pairings (memory, SQLite,
PostgreSQL continuation store), plus one isolation-control test over the same
three pairings. Each matrix node proves, against the crash residue itself:

- reachability: the split state is built as the window leaves it — a parked Run
  (timer WAITING with an unelapsed `resume_at`, or PAUSED with a durable HITL
  pause entry and its lookup projections) whose resumed walker wrote its
  terminal continuation and lost every spine write behind it;
- visitation: a spy on the sweep's per-Run repair records the row being
  enumerated and evaluated (through the canonical parked scan and the terminal
  continuation buckets), not merely absent from the changed count;
- preservation: canonical parked status, terminal continuation status and
  version, pending-decision evidence, and the completed NodeRun (with its
  accepted Attempt outcome) are all intact after the tick;
- isolation and idempotence: a genuinely repairable Run — the stale RUNNING
  continuation under a canonically terminal COMPLETED Run that
  `_reconcile_terminal_spine` owns — settles in the same bounded sweep
  (exactly one change), all four parked rows refuse unchanged, and the next
  tick re-derives zero.

Executed 2026-10-18 at the lane head: 15 passed with
`MAISTRO_TEST_PG_DSN` set (pgvector/pg18 container, alembic head), 10 passed /
5 skipped (postgres legs) without it.
