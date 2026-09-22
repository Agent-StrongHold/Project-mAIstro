inventory-delta:
  packages/hive-conductor/backend/tests: +1 (1 strengthened in place, 1 strengthened via moved declaration)
---

# Auto-1085 repair 4: request-shaping parity and one binding-declaration authority

Fourth repair round for #1085, closing the two code findings from the
2026-09-07 verification (`NEEDS-REPAIR`):

- `legacy_dag_node.py::_governed_model_call.call` rebuilt the provider-neutral
  request with only model/messages/temperature/max_tokens, dropping the
  historical callable's `response_schema` support, the always-sent
  `response_format` (default `json_object`), and tool forwarding. The adapter
  now shapes the request exactly like the raw-HTTP path it replaced
  (`json_schema` when `response_schema` is supplied, else `json_object`) and
  forwards `tools`; the effect-key material includes the shaping so two calls
  differing only in shaping cannot collide.
- The operator's default-binding declaration was split: the bridge provisioned
  the PASSED `Settings.maistro_model_binding_id`, while nodes resolved the
  default from ambient environment/cached-global settings, so a passed
  declaration could be provisioned yet unresolvable. The declaration now lives
  once on the composed runtime config (`AgentConfig.default_model_binding_id`),
  the bridge provisions from it, and `canonical_dag_runner` forwards that same
  value into every node's wiring (`MAISTRO_MODEL_BINDING_ID` in `_node_env`),
  so provisioning and node resolution read one authority.

Test deltas:

- `test_legacy_dag_node.py`:
  `test_governed_call_preserves_the_legacy_request_shaping_contract` (NEW)
  captures the gateway payload through the governed egress and pins the
  default `json_object` shape, the `response_schema` -> `json_schema` shape,
  forwarded `tools`, and the persisted Invocation evidence carrying the same
  shaping.
- `test_canonical_dag_runner.py`:
  `test_node_env_carries_the_composed_default_binding_declaration` (NEW) pins
  `_node_env`'s new `model_binding_id` wiring and
  `_deployment_model_binding_id` reading the composed container config.
- `test_maistro_core_adapter.py`:
  `test_start_provisions_the_declared_default_model_binding` now declares the
  binding ONLY through the passed `Settings` kwarg with the ambient env var
  deleted -- the exact probe that previously resolved an empty binding -- and
  asserts the composed runtime config carries the declaration end to end.
