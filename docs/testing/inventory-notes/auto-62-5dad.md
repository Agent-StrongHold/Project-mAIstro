---
inventory-delta:
  packages/maistro-core/tests: -3
---
# auto-62-5dad

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
