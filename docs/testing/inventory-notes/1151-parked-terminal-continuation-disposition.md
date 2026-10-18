---
inventory-delta:
  packages/maistro-core/tests: +15
---

# 1151 parent-held characterization: parked canonical x terminal continuation rows

`tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`
delivers the parent-held parked-conflict characterization from #1151's dispatch
scope: four constructed `WAITING/PAUSED x COMPLETED/FAILED` inputs, their
pending-decision/HITL evidence, and a second repairable Run proving isolation.
These direct store constructions do **not** prove that a production walker can
reach every row, or satisfy the parent's blocked disagreement-repair criterion.

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
and PostgreSQL), plus one isolation-control test over the same three pairings.
The current repair replaces the PG-continuation/InMemoryRunStore pairing with
PgRunStore + PgGraphContinuationStore, backed by PgProjectScopeStore. Recovery
uses an independent pool; its complete assembled-record reads verify committed
Run/NodeRun/Attempt evidence, not a shared in-memory spine. No new collected
nodes, so the existing +15 inventory delta remains unchanged.

Each matrix node proves:

- input persistence: a constructed parked Run (timer WAITING with `resume_at`
  still in the future at the explicitly passed evaluation clock, or PAUSED with
  a durable HITL pause entry) under a terminal continuation can be independently
  read by recovery; this is not an injected production-walker crash;
- visitation: a spy on the sweep's per-Run repair records the row being
  enumerated and evaluated (through the canonical parked scan and the terminal
  continuation buckets), not merely absent from the changed count;
- preservation: canonical parked status, terminal continuation status and
  version, pending-decision evidence, and the completed NodeRun (with its
  accepted Attempt outcome) are all intact after the tick; the full assembled
  record, including physical Attempt history, is equal before and after both
  reconciliation calls;
- isolation and idempotence: a genuinely repairable Run — the stale RUNNING
  continuation under a canonically terminal COMPLETED Run that
  `_reconcile_terminal_spine` owns — settles in the same bounded sweep
  (exactly one change), all four parked rows refuse unchanged, and the next
  tick re-derives zero.

Earlier lane executions used the mixed PG-continuation/in-memory-spine fixture.
They are not dual-PG durability evidence. Current repair validation and remaining
acceptance gaps are recorded in `docs/testing/1151-repair-current.md`.
