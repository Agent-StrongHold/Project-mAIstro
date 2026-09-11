---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +111
---
# fix-m1-1193-synth-dag-required-authorities-0036

One test was replaced and the rest are new; the large core count is three
parametrized guards fanning out over every registered node kind, not a
hundred hand-written cases. In
`packages/maistro-core/tests/graph/nodes/test_agent_synth_dag.py`,
`test_llm_call_without_a_store_declines_execution_honestly` — which pinned the
defect, a `success=True` output for a sub-graph nothing ran — is replaced by
`test_a_node_built_without_a_store_fails_loudly_rather_than_reporting_success`
(net zero); three approval tests there now construct the node with a durable
store, since approval with no store is no longer a completed result. The new
`test_node_composition.py` holds the mechanism: per registered kind (18 today,
so 54 collected), every declared authority is one the resolver can supply and
names a real constructor parameter, a fully wired resolver hands the kind the
exact sentinel instances it declared and nothing it did not, and a bare
resolver refuses every kind with a required authority with
`NodeCompositionError` while still constructing the rest. Beside those, two
registration guards (unknown authority, unknown keyword), a refusal that names
the missing authority, three `build_node_resolver` regressions for
`agent.synth_dag` (both stores and the resolver itself handed on; refused
without them; neither store standing in for the other), and three
production-composition cases through a real Container: the node's stores are
the Container's own `graph_run_store` and `run_store`, a node obtained through
`Container.node_resolver()` admits and completes a child Run on the canonical
spine under its parent Run and NodeRun, and a Container with the graph store
unwired is refused rather than degraded. The two hive additions in
`packages/hive-conductor/backend/tests/test_dag_agents.py` prove the bridge
hands `agent.synth_dag` the durable graph store (not the canonical one) and
that the standalone fallback resolver refuses the kind outright.
