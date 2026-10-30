---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +3
---
# auto-62-5dad

## Round 2 (this round): governed harness polls and a fair paused sweep

Cumulative front-matter: the develop-sync round below recorded net −3 core;
this round adds 6 collected core cases and 1 hive case, so the branch note
now records +3 core (−3 + 6) and +1 hive.

- `test_m1_e2_recovery_convergence.py` +3: the external harness seam now
  polls a provider only on behalf of its governed dispatch — the pause must
  carry the node-persisted dispatch Invocation and Binding reference, the
  receipt must correlate with the Run, and the Binding must still resolve.
  Cases: revoked Binding never polled, unevidenced pause never polled,
  missing/foreign receipt never polled; the two pre-existing delivery cases
  were rewritten to carry production-shaped wait evidence.
- `test_cross_store_crash_reconciliation.py` +3 collected (memory/sqlite/pg
  fixtures): a persistent canonical-PAUSED Run can no longer consume every
  tick's budget — the paused page rotates like the RUNNING page, so a
  failed-publication terminal Event is still discovered behind parked work
  at limit=1 (fails against the old from-the-top scan, 0 events).
- `test_registered_dag_recovery.py` +1: registered harness admission, real
  Binding revoked mid-wait, then `wake_due_registered_dag_runs(limit=1)`
  before the timer: the provider is never read, no protected output is
  persisted, and the later timed resume fails truthfully instead.

## Round 1 (develop sync)
Develop-sync repair for CR1373 (#1373). The lane's stale rebuild had replaced
several develop test files with older whole-file versions; this round restored
the develop versions and re-applied only the lane's genuine additions, so the
maistro-core suite moves net −3 against develop's recorded inventory:

- `tests/graph/durable_runs/test_answer_gated_recovery.py`: back to develop's
  two remote/human deadline tests. The lane's variant asserted a
  system-pause-timer semantics (`awaiting_remote_delegation` → WAITING with a
  persisted `resume_at`) that neither develop's nor the lane's own
  `PAUSE_REASON_OWNERS` table implements; develop's pinned disposition
  (human-owned, PAUSED, deadline carried as HITL evidence for
  `expire_hitl_pauses`) is what the merged source does, and
  `test_pause_reason_wakers.py` pins the waker mapping mechanically.
- `tests/graph/durable_runs/test_hitl_settlement.py` and the other clobbered
  files: develop's hardened authorization coverage restored (the lane's
  copies had dropped the `authorization=` seams develop's tests pin).
- Additions kept: `tests/graph/durable_runs/test_m1_e2_recovery_convergence.py`
  (+7, the lane's crash-window and external-waker contracts) and
  `tests/a2a/test_delegate.py::test_terminal_task_completion_notifies_the_injected_canonical_waker`
  (+1). `tests/graph/nodes/test_agent_delegate_remote.py` keeps the lane's
  metadata assertion, now against the merged delegation-key + parent-pointer
  metadata.
