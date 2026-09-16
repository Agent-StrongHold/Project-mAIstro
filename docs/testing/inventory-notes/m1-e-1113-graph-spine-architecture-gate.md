---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---

# M1-E #1113 Graph-spine architecture gate

Adds `packages/hive-conductor/backend/tests/test_graph_spine_architecture_gate.py`:
an AST gate over the shipped Hive backend (everything but `tests/`) that fails
if any shipped module calls `run_durable_graph(...)` without a non-None
`run_store=` admission kwarg, or imports/references `InMemoryDurableRunStore`,
`_fallback_run_store`, or `_fallback_node_resolver`. This is the source-level
complement to the behavior tests from the main #1113 note: it fires on the
regression pattern itself, not only when a test happens to exercise it.
Verified by mutation against `develop`'s pre-fix `dag_agents.py` (all three
forbidden names detected at their historical lines) and against synthetic
`run_store=None` / omitted-kwarg calls.
