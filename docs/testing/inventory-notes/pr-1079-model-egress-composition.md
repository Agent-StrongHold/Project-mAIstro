---
inventory-delta:
  packages/maistro-core/tests: +3
---
# issue-1079-model-egress-composition

M1-D2 production composition repair for governed model egress (#1079). The
lane adds three collected tests in
`packages/maistro-core/tests/test_model_egress_container_composition.py`:

- configured model Bindings load through the production Container bootstrap,
  with blank Workspace scope inheriting `AgentConfig.workspace_id`;
- an empty declaration set authorizes no model Binding and fails closed;
- a Container-resolved `llm.summarize` receives the exact effect context,
  Provider registry, and router owned by the Container, then crosses the real
  Binding -> Invocation path with registry-derived cost and Run/NodeRun/Attempt
  correlation before refusing a wrong-Workspace request without dispatch.

The transport is replaced only at the final physical model seam; the test does
not write directly to the Binding store.
