---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
  packages/maistro-server/tests: +7
---

# #1824 installed model configuration reaches the runtime's Binding and gateway credential

Seventeen node IDs in
`packages/hive-conductor/backend/tests/test_effective_gateway_key.py` (new) and
seven in `packages/maistro-server/tests/test_worker_yaml_config_startup.py`
(new). Two existing server node IDs were rewritten in place
(`test_startup.py::TestRouterApiKeyValidation`, same count): they pin the
environment-only ROUTER_API_KEY refusal, which now requires pinning the YAML
singleton to None, because the worker — correctly — loads the documented
config into it during every lifespan boot.

**Hive +17** pin the one effective-key contract
(`services.secrets.effective_llm_gateway_key`): the precedence matrix
(only-`MAISTRO_LLM_API_KEY`, only-`LITELLM_API_KEY`, both supported proxy
aliases, alias ordering, vault-first on both names, conflict resolution,
empty-string-falls-through, none-is-`None`); `sk-noop` removal (the legacy
roster client refuses complete/stream *before any HTTP* when unconfigured,
with a sanitized message carrying no key material); the embedded runtime
building its roster client and governed endpoint from the effective key (and
holding no key at all when nothing is configured); and the governed egress
endpoint resolving the same credential through the same contract as the roster
client.

**Server +7** pin the worker-side config load: missing file starts empty and
fail-closed (the pinned parser contract); the worker loads the documented YAML
before `_validate_startup` and `_agent_config` (the YAML alone satisfies the
ROUTER_API_KEY check, and the declared Binding resolves through the real
Container's bootstrap + scope routing); malformed and type-invalid explicit
configs refuse startup before any Container is built, with a sanitized message
that never echoes file content; and two fresh-subprocess proofs run the real
shipped lifespan in a clean worker process — one loading the documented config
and resolving the Binding with no test singleton injection, one refusing a
malformed file before dispatch.
