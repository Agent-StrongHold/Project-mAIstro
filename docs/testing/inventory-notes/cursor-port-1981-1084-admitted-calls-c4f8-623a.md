---
inventory-delta:
  packages/maistro-core/tests: +32
---
# cursor-port-1981-1084-admitted-calls-c4f8-623a

Port of stale draft #1981 onto current `develop` for #1084 (M1-D2).

## packages/maistro-core/tests (+32)

Added focused admission and delegation suites over the shared
`tests/_admitted_model_fixture.py`, and retargeted existing governed-client
cases onto `GovernedLLMClient(AdmittedModelCalls)`:

- `test_governed_llm_admission.py` — Agent client joins configured Binding /
  persisted actor, refuses invented correlation and revoked Bindings, incremental
  stream + replay revocation (includes parametrized refusal matrix), plus
  `test_agent_stream_replay_preserves_tool_calls_and_finish_reason` (+1 over the
  prior +31 port note) so effect-deduplicated replay keeps structured deltas.
- `test_governed_delegation.py` — distinct `agent-llm:{name}:{depth}:{seq}`
  effects for model-before-delegate chains, plus original `set_turn` compatibility.
- Factory composition cases rewritten from four-authority wrapping to
  `admitted_calls` composition.
- Identity / tool_choice / quota / egress adopt-context cases retargeted onto
  the admitted client.

Hive bridge tests were rewritten for the same wiring (admitted_calls endpoint /
`llm._calls`) without a net inventory delta after refresh.

Evidence notes (no inventory-delta): `1084-agent-admission-binding-actor.md`,
`1084-agent-delegation-effects.md`, `1084-hive-agent-admitted-calls.md`.
