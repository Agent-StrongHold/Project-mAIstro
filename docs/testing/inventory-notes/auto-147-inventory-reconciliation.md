---
inventory-delta:
  packages/maistro-core/tests: -6
---
# auto-147-inventory-reconciliation

No test was added or removed by this note. It corrects this branch's own
ledger: the auto-147 notes collectively recorded +16 collected nodes for
`packages/maistro-core/tests`, but the branch's true addition over develop
(`e15706ced`) is +10; the other six were counted as additions when they were
renames or re-parametrizations of tests develop already counts. The ledger
compares counts, not node IDs, so a rename moves nothing — recording the new
name as +1 while develop's note still counts the old name double-counts one
test as two. Measured at this branch: expected 10645, collected 10639.

The six compensating pairs (develop name -> this branch's name, one collected
node each, both sides of every pair counted before this correction):

- `test_answer_gated_recovery.py` — the three `test_system_owned_answer_wait_*`
  / `test_answer_deadline_is_persisted_*` names became
  `test_remote_answer_wait_*` / `test_remote_answer_deadline_is_persisted_*`
  when the wait stopped being system-owned and became an answer-gated PAUSED
  record.
- `test_agent_delegate_remote_review.py` —
  `test_the_answer_settles_the_child[timed_out-timed_out]` became
  `test_the_answer_settles_the_child[timed_out-failed]` when the peer's
  `timed_out` answer stopped being echoed as the child's terminal state;
  `test_an_inline_subgraph_is_snapshotted_as_the_work` became
  `test_an_inline_subgraph_is_recorded_as_untransmitted_request_context` when
  the child snapshot stopped claiming an untransmitted subgraph as work.
- `test_human_pause_reasons.py` — `awaiting_remote_delegation` moved from
  `EXPECTED_SYSTEM` to `EXPECTED_HUMAN`, trading
  `test_a_system_wait_is_not_a_human_pause_on_either_path[awaiting_remote_delegation]`
  for `test_every_human_reason_is_a_human_pause_on_both_paths[awaiting_remote_delegation]`.
