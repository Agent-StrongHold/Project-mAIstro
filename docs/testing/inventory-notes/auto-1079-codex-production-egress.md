---
inventory-delta:
  packages/maistro-core/tests: +9
---
# #1079 review: model egress reaches production, credentials, and a durable ledger

- `config/test_model_binding_config.py` (+4): a misspelled Binding restriction
  (`provider_nam`, `nodeid`, `credential_ref`) refuses the declaration
  directly and at the `AgentConfig` boundary (`extra="forbid"`).
- `capabilities/test_model_chat_egress.py` (+3): an alias passes through to
  the gateway when no model metadata is registered at all (a populated
  registry still refuses unknown aliases); a Binding that declares
  `credential_refs` authenticates the call with the scoped credential and
  never persists it; refs with no scoped credential fail closed before any
  gateway call.
- `test_model_egress_container_composition.py` (+2): a Container-resolved
  `llm.summarize` uses `AgentConfig.litellm_url`/`litellm_key` with the
  environment cleared; a SQLite Container's capability Invocation ledger
  survives a restart.

The Hive resolver test additionally asserts the node receives the Container's
`gateway_endpoint` (extended assertion, no count change).
