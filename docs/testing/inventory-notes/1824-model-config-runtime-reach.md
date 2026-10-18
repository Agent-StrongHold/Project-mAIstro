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

## Develop-merge reconciliation (no node-ID delta)

The branch was synced to develop `2f56be40a` (merge `b3b386da5`). The merge
kept this note's +17/+7 exactly: no node IDs were added, removed or renamed by
the reconciliation, so the front-matter deltas above are unchanged. Three
develop-side test files predated the one-contract contract and were repaired
for stub fidelity / cache hygiene, not for behavior:

- `test_effective_gateway_key.py` — develop's `AdmittedModelCalls` wiring in
  `_construct_runtime` reads `container.run_store`/`provider_adapter_catalog`
  (real Container attributes, always present); the two runtime-construction
  stubs now mirror them. `test_endpoint_resolves_the_effective_key` gained the
  same `get_settings.cache_clear()` hygiene its sibling already documented:
  develop's e2e module seeds the lru-cached Settings with its own gateway key,
  which otherwise outranks the alias this test states.
- `test_provider_pin_registration.py` — the `get_settings` stub now carries
  `maistro_llm_api_key`, mirroring what pydantic-settings produces from the
  env the same fixture sets (the effective-key contract reads that field).
- `test_graph_runner.py` — the `_S` settings stub carries
  `maistro_llm_api_key` (unconfigured), mirroring the real Settings field the
  governed `_endpoint` reads on the canonical DAG path.

The `tests/` suite drift this merge reports (`expected 5260, collected 5261`)
is inherited from develop's tip, not introduced here: `tests/`,
`baseline.json`, `pyproject.toml` and the root conftest are byte-identical to
develop, and develop collects the same 5261.
