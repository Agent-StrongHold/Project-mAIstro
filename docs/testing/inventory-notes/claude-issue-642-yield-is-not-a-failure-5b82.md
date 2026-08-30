---
inventory-delta:
  packages/maistro-core/tests: +5
---
# claude-issue-642-yield-is-not-a-failure-5b82

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Five added, none removed, none rewritten.

Four are `tests/runtime/test_pause_is_not_a_failure.py`, the new file for
SPEC-081426-1f7c AC-13..AC-16: a pause increments the pause count and no other
terminal count (one test, because three of the four criteria are about counts
that must *not* move and a per-field assertion cannot see one that moved
somewhere nobody looked); a genuine error is still a failure and not a pause;
a pause re-raises and leaks no slot; and `runs.ExecutionYielded` is a subclass
of the signal Runtime counts.

That last one is the load-bearing test rather than a formality. The counter is
reached by `ExecutionPaused`, and the class anything actually raises is
`ExecutionYielded`. Break the subclass relationship and the other four still
pass while the defect is entirely back.

The fifth is in `tests/runs/test_execution.py`, going through
`AttemptExecutionService` end to end: the Attempt terminalizes YIELDED *and*
the runtime records a pause. The bug was the two records of one event
disagreeing, so one of the tests has to be able to see both.
