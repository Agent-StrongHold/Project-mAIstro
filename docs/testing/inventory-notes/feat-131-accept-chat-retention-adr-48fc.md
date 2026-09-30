---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# feat-131-accept-chat-retention-adr-48fc

Six hive-conductor behavioral tests in `test_chat_run_admission.py`, all
covering the Workspace chat-window fix this PR carries alongside the ADR.

That fix is production code, not documentation: Hive keeps one
`ChatRunAdmitter` per Workspace, while `Container._close_chat_run` sweeps a
different admitter, so a Hive turn that ended with no later admission sat past
`max_retained` indefinitely. A dispatch shield, set while the Run is QUEUED,
stops a concurrent sweep deleting an Attempt-less RUNNING turn; `_settle_window`
releases it and re-applies the Workspace's window once the turn settles.

**The first three** pin the behaviour: the admitter forgets completed turns when
the turn ends rather than only on the next admission, a still-running turn is
not swept before its Attempt exists, and admission records the request id.

**The last three** cover the failure paths the diff-coverage gate found
uncovered, and one of them is the only way the shield could leak:

- a failed move to RUNNING, *after* the shield was set, must release it --
  otherwise the cancelled Run stays exempt from its Workspace's retention sweep
  for the life of the process;
- a failed shield release must not skip the sweep, which is the retention bound
  the fix exists to restore;
- a failed sweep must not escape `execute_turn`'s `finally`, where it would turn
  an answered turn into an error.

No other suite count moved.
