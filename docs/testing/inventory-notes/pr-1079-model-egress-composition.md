---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/maistro-server/tests: +2
  packages/hive-conductor/backend/tests: +1
---
# issue-1079-model-egress-composition

M1-D2 production composition repair for governed model egress (#1079). The
lane adds collected tests at three layers of the same composition seam:

`packages/maistro-core/tests/test_model_egress_container_composition.py`
(5 tests — this note's core delta counts exactly this file):

- configured model Bindings load through the production Container bootstrap,
  with blank Workspace scope inheriting `AgentConfig.workspace_id`;
- an empty declaration set authorizes no model Binding and fails closed;
- a Container-resolved `llm.summarize` receives the exact effect context,
  Provider registry, and router owned by the Container, then crosses the real
  Binding -> Invocation path with both pinned and unpinned registry selection,
  registry-derived cost, and Run/NodeRun/Attempt correlation before refusing a
  wrong-Workspace request without dispatch;
- the Container's own consumer tick (`execute_admitted_runs`) admits and
  completes a single-node `llm.summarize` Run whose authorization was loaded
  through the production `bootstrap_model_bindings` registration path, with
  unpinned router selection, registry-derived cost, and Invocation evidence
  correlated to Run/NodeRun/Attempt — the node here is built by the tick's
  internally wired resolver, not by a resolver the test assembled;
- the twin: with the registration step removed, the same Run records a
  failed NodeRun carrying `BindingNotFound`, dispatches nothing physical, and
  persists no Invocation.

`packages/maistro-core/tests/config/test_model_binding_config.py` (+6, counted
under the session note `auto-1079-ad81.md`): the YAML layer carries raw
declaration maps and the `AgentConfig` boundary validates them into
`ModelBindingConfig`, so blank identity/scope or empty refs are startup
failures rather than unresolvable Bindings.

`packages/maistro-server/tests/api/test_conductor_agent.py` (+2): the server's
explicit `_agent_config` mapping carries declared `model_bindings` from
`MaistroYamlConfig` into `AgentConfig`, and a deployment with no loaded YAML
declares no authorization (fail-closed default).

`packages/hive-conductor/backend/tests/test_dag_agents.py` (+1): the Hive
node-resolver bridge builds `llm.summarize` from the Container's own
effect context, Provider registry, and router (identity asserts), so a
registered DAG cannot fall back to fresh empty authorities that would make
configured Bindings invisible.

The transport is replaced only at the final physical model seam; no test
writes directly to the Binding store.
