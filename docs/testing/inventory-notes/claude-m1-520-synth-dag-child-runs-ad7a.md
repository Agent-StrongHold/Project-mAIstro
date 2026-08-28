---
inventory-delta:
  packages/maistro-core/tests: +6
---
# claude-m1-520-synth-dag-child-runs-ad7a

Six new tests in `tests/graph/nodes/test_agent_synth_dag.py` for #520's
canonical child-Run dispatch: a registered-kind config runs as a child Run with
parent linkage, canonical NodeRun/Attempt records and threaded `synth_depth`;
a role-shaped config with a store declines with the reason; an unscoped context
declines rather than inventing scope; a config with duplicate node kinds and one
whose entry is outside the synthesized nodes both decline with the reason; and
`_node_kind` resolves later nodes while refusing unknown ids. One existing test was rewritten in place
(`test_execution_runs_synthesized_graph_when_llm_call_provided` became
`test_llm_call_without_a_store_declines_execution_honestly`) and the
failed-subgraph depth test in `test_durable_runs.py` now fails its child Run
canonically instead of monkeypatching the retired `run_graph` path. Purely
additive in count; no test was removed.
