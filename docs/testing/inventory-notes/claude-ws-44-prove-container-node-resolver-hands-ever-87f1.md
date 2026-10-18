---
inventory-delta:
  packages/maistro-core/tests: +6
---
# claude-ws-44-prove-container-node-resolver-hands-ever-87f1

`packages/maistro-core/tests/graph/nodes/test_container_node_composition.py` is
new (#44, #1082): one coverage check that the sweep's authority-to-Container
mapping covers every authority a shipped kind declares, plus one parametrized
case per shipped kind that declares an authority (`agent.delegate_remote`,
`agent.spawn_harness`, `agent.synth_dag`, `llm.summarize`,
`rsi.quota_pace_trigger`), each resolved through a real Container's
`node_resolver()`. Nothing was removed or moved.
