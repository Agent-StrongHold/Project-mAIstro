---
inventory-delta:
  packages/maistro-core/tests: +3
---
# pr-1091-m1-1079-model-egress-composition

M1-D2 production composition repair for governed model egress (#1079, PR #1091).
The lane adds three collected tests in
`packages/maistro-core/tests/test_model_egress_container_composition.py`:

- configured model Bindings are loaded by the production Container bootstrap,
  with blank Workspace scope inheriting `AgentConfig.workspace_id` while an
  explicit Workspace remains explicit;
- an empty declaration set authorizes no model Binding and fails closed;
- a Container-resolved `llm.summarize` receives the Container's exact effect
  context, Provider registry, and router; the test executes the governed
  Invocation seam with a fake physical transport, proves registry-derived cost
  plus Run/NodeRun/Attempt correlation, and proves a wrong Workspace is refused
  before transport dispatch.

The transport is replaced only at the final physical HTTP seam so the proof
still exercises the real Container bootstrap, Binding resolution, Provider
selection, governed Invocation service, Invocation store, and usage extraction.
