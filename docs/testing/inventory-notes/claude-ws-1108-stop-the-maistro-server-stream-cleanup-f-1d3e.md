---
inventory-delta:
  packages/maistro-server/tests: +1
---
# claude-ws-1108-stop-the-maistro-server-stream-cleanup-f-1d3e

One test added, none removed (#1108). `packages/maistro-server/tests/api/test_chat_completions_gate.py`
gains `test_a_stream_does_not_cancel_a_run_left_open_for_recovery`: a streamed turn whose
Attempt COMPLETED write fails after the model answered must leave its Run RUNNING (not
CANCELLED as "stream abandoned") so `recover_abandoned_attempts` can still settle it, with
exactly one model call.
