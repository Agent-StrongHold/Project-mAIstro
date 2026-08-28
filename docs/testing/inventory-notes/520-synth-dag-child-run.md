---
inventory-delta:
  packages/maistro-core/tests/: +3
---

# #520 synthesized child-Run convergence coverage

Adds three durable-Graph tests for the `agent.synth_dag` convergence slice: a synthesized role executes as a persisted child `Run` with the dispatching parent `Run` and `NodeRun` identities, every child node crosses the canonical `NodeRun` + `Attempt` boundary, and Workspace/Project scope plus child provenance remain attached to the child Run.

A recursive synthesis test proves `synth_depth` is carried across the child-Run boundary and incremented before nested execution: with `max_depth=1`, the parent may create one child Run, the child synth node refuses to create a grandchild, and the shared durable store contains exactly those two Runs.

A static regression test covers both `graph/durable_runs/` and `graph/nodes/` and fails if a production `run_graph(...)` caller reappears in the durable execution tree. The compatibility AgentRole adapter executes under the canonical child Attempt and does not instantiate the legacy `GraphRun`/legacy `NodeRun` lifecycle.
