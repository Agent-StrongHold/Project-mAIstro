---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/hive-conductor/backend/tests: +6
---
# claude-glm-issue-63-m1-e3-convergence-tail

Issue #63's remaining implementable surface, after #707 (correlation context),
#717 (spend-bullet disposition) and #836 (emit authority) had landed: the
Workspace/Project legs of the ambient chain, the end-to-end proof the
acceptance list asks for, and the wiring the reachability dispositions had
assigned to #63 by name.

## packages/maistro-core/tests (+4)

- `graph/durable_runs/test_durable_run_is_correlated.py` +2: the durable walk
  binds its Workspace and Project beside its Run (zero-cost; the record is in
  hand), and an event emitted inside the run fills `project_id` from that
  context rather than only from a hand-spelling producer.
- `graph/durable_runs/test_child_runs.py` +1: the delegation leg of AC-2 — a
  child run's events name the child, not the parent attempt that launched it,
  while `parent_run_id` stays the durable join in one Workspace stream.
- `integration/test_one_trace_end_to_end.py` +1 (new file, 2 tests counted as
  the file's suite; delta recorded per file): the whole chain request → Run →
  NodeRun → Attempt → Event/Outcome through the real spine and a durable
  SQLite event store, plus the retry leg joining the same trace. The
  Invocation link stays the documented #55 exception.

## packages/hive-conductor/backend/tests (+6)

- `test_privilege_middleware_installed.py` +3 (new file): the privilege
  boundary is installed on the real app, inside the authenticated boundary,
  and its empty policy table passes health through unchanged.
- `test_adapter_ports.py` +3: both telemetry backends satisfy the (now
  runtime-checkable) `TelemetryPort`; the chat path holds the composed port
  singleton rather than the concrete backend; the engine's one agent-port
  assignment point checks the `AgentPort` contract and refuses a non-port.

`test_chat_streaming.py` changed without a delta: six monkeypatch sites moved
from the removed `services.chat_completion.trace_llm` attribute to the
composed `telemetry` port seam, preserving each test's captured-boundary
intent. Same tests, different patch point.
