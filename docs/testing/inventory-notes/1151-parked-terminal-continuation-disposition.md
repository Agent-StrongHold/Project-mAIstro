---
inventory-delta:
  packages/maistro-core/tests: +15
---

# 1151 parent-held characterization: parked canonical x terminal continuation rows

`tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`
delivers the parent-held parked-conflict characterization from #1151's dispatch
scope: four constructed `WAITING/PAUSED x COMPLETED/FAILED` inputs, their
pending-decision/HITL evidence, and a second repairable Run proving isolation.
The production walker now creates each timer/HITL park through physical
execution and canonical acceptance; only the terminal-continuation mismatch is
constructed. This does **not** prove that a production walker can reach every
conflicting pair, or satisfy the parent's blocked disagreement-repair criterion.

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

- input persistence: `run_durable_graph` executes a pausing node once and writes
  its completed physical Attempt, accepted WAITING/PAUSED logical NodeRun and
  parent, and timer/HITL continuation. Recovery independently reads that park
  before the terminal mismatch is injected. Timer deadlines are in the future
  at the explicitly passed evaluation clock; no HITL answer or settlement exists.
  This is not an injected production-walker crash;
- visitation: a spy on the sweep's per-Run repair records the row being
  enumerated and evaluated (through the canonical parked scan and the terminal
  continuation buckets), not merely absent from the changed count;
- preservation: canonical parked status, terminal continuation status and
  version, pending-decision evidence, and the parked NodeRun (with its
  accepted completed physical Attempt outcome) are all intact after the tick;
  lease identity is checked and the full assembled record, including physical
  Attempt history, is equal before and after both reconciliation calls;
- HITL authority: public `resume_durable_graph` refuses PAUSED rows before
  resolving a node, even under a terminal continuation; neither canonical
  history nor the raw continuation changes;
- isolation and idempotence: a genuinely repairable Run — the stale RUNNING
  continuation under a canonically terminal COMPLETED Run that
  `_reconcile_terminal_spine` owns — settles in the same bounded sweep
  (exactly one change), all four parked rows refuse unchanged, and the next
  tick re-derives zero.

Earlier lane executions used the mixed PG-continuation/in-memory-spine fixture.
They are not dual-PG durability evidence. Current repair validation and remaining
acceptance gaps are recorded in `docs/testing/1151-repair-current.md`.
The current walker-backed fixture repair and its validation are recorded in
`docs/testing/1151-repair-20261018-current.md`. Collected node count remains 15;
the existing inventory delta is unchanged.
