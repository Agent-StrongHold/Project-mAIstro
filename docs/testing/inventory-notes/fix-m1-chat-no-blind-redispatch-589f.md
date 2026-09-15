---
inventory-delta:
  packages/maistro-core/tests: +6
---
# fix-m1-chat-no-blind-redispatch-589f

Six new behavioral tests in
`packages/maistro-core/tests/runs/test_chat_execution.py`
(`TestAPostDispatchRecordingFailureIsNeverRedispatched`) for the second
defect in #1108; nothing was removed or moved. Each injects a one-shot
`RunIntegrityError` on a spine write and counts dispatches: a failed Attempt
COMPLETED write returns the answer once, leaves the Run open, and is reclaimed
by `recover_abandoned_attempts` with no second model call; a failed NodeRun
reconciliation after a completed Attempt is repaired by
`AttemptLifecycleReconciler` from the durable evidence, again with one
dispatch; a dispatch that itself failed and then could not be recorded still
arrives as the dispatch's own exception; a spine refusal *before* the model
call but inside the executor (the Attempt's RUNNING write) still falls back to
answering exactly once; and two executor-level cases pin the signal the
container reads — `ChatDispatchUnrecorded` carrying the answer for a
post-dispatch failure, plain `RunIntegrityError` for one before the dispatch.
The pre-existing pre-dispatch fallback test is unchanged.
