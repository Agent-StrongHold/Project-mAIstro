---
inventory-delta:
  packages/maistro-server/tests: +4
---
# claude-ws-1108-stop-the-maistro-server-stream-cleanup-f-1d3e

Four tests added, none removed (#1108), all in
`packages/maistro-server/tests/api/test_chat_completions_gate.py`, pinning when the SSE
stream's abandoned-Run cleanup (`_close_if_open`) must and must not cancel:

- `test_a_stream_does_not_cancel_a_run_left_open_for_recovery` — Attempt COMPLETED write
  fails after the answer: Run stays RUNNING over a RUNNING Attempt, one model call, and
  `recover_abandoned_attempts` still settles it.
- `test_a_stream_leaves_a_completed_attempt_for_the_reconciler` — NodeRun reconcile fails
  after a COMPLETED Attempt: Run and NodeRun stay RUNNING for the reconciler.
- `test_a_refused_stream_whose_close_failed_is_still_cancelled` — pre-dispatch refusal
  (NodeRun, no Attempt) whose own close failed is still cancelled by the cleanup.
- `test_a_failed_stream_whose_close_failed_is_still_cancelled` — a FAILED Attempt whose
  Run close failed is still cancelled by the cleanup.
