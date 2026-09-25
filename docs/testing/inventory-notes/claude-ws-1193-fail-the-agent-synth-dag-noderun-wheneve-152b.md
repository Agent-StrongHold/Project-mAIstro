---
inventory-delta:
  packages/maistro-core/tests: +6
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
- `tests/graph/durable_runs/test_durable_runs.py`: +2 more — a failed synth
  node whose child was dispatched still spends its recursion level: one walk
  retries it (`max_attempts: 2`, child depths 1 then 2) and one continues past
  it (`continue_on_failure`, successor sees depth 1).
- `tests/graph/durable_runs/test_executor_mutants.py`: +2 — `_actually_spawned`
  counts a failed synth result with `dispatched` metadata, and not one without.
