---
inventory-delta:
  packages/maistro-core/tests: +2
---
# claude-ws-1193-fail-the-agent-synth-dag-noderun-wheneve-152b

#1193 owner decision: `agent.synth_dag` fails its NodeRun whenever it
dispatches nothing or its child Run does not complete.

- `tests/graph/nodes/test_agent_synth_dag.py`: +1 —
  `test_a_failed_child_run_fails_the_node_naming_the_child` is new; the
  existing refusal/decline tests were inverted in place (same count) to assert
  a FAILED `SynthDagFailed` NodeResult instead of a COMPLETED output flag.
- `tests/graph/durable_runs/test_durable_runs.py`: +1 — the depth-cap walk
  test and the "refused synth does not increment depth" test collapsed into
  one (a refusal now fails the Run, so there is no next node to observe), and
  two new walks pin the blocked-shape and outside-allowlist cases as FAILED
  NodeRuns with no child Run. The failed-subgraph test was inverted in place.
