---
inventory-delta:
  packages/maistro-core/tests: +5
---

# #66 A2A resume-boundary scans

Resumed `agent.delegate_remote` answers are remote peer output, so `result`,
`error` and `task_id` now cross a Warden `tool_result` boundary inside the node
before they re-enter trusted Run/Agent context (#66 / #1137): a refused payload
reads as a failed delegation and is never relayed, the child Run settles
`failed`, and the guest-peer fast-fail error string is scanned the same way.
The node default-constructs its Warden (same posture as `agent.synth_dag`), so
no construction path — bare registry included — can ship without the boundary.

Also repaired `test_log_redaction.py::test_install_is_idempotent` (no count
change): its `install_log_redaction(...) == 0` assertion assumed no handler can
appear between fixture setup and the test body, which pytest's own logging
plugin violates by attaching capture handlers to non-propagating loggers; the
test now asserts the real per-handler no-double-wrap invariant. The whole
`tests/security` suite (1196 tests) passes with this repair.

New tests: four resume/dispatch refusal cases in
`tests/graph/nodes/test_agent_delegate_remote.py` and one child-Run
terminalization case in `tests/graph/nodes/test_agent_delegate_remote_child_run.py`.
