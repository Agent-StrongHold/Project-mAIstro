---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# #718 repair: the Evolve production cycle crosses the canonical model authority

The prior verifier round pinned the last unrecorded production model-egress
class: `services/evolution.py`'s `_build_llm_call()` returned a raw
`/v1/chat/completions` poster handed straight to
`run_canonical_evolution_cycle`, reachable from `routes/evolution.py`
(`/evolution/cycle`, the cadence task, and the #1064 restart-recovery
resolver). Every production Evolve model call therefore bypassed
Binding/Invocation/quota recording while per-provider ledger rows presented
as complete — the exact "ordinary production calls do not enter the ledger"
defect #718 exists to close.

## What changed

- `services/evolution.py` — `_build_llm_call()` now resolves the engine
  bridge's `governed_egress` (the same `ModelChatEgress` authority the roster
  clients, the conductor, and the demo task executor already cross) and, when
  present, returns a governed closure:
  - Binding over the Container's Workspace, the shared `agent-runtime`
    project, `model.chat` capability, and the bootstrapped default gateway
    credential ref — fail-closed acquisition like every other governed call;
  - cycle-scoped `run_id`/`node_run_id` with per-call unique
    `attempt_id`/`effect_key`, so completed effects record exactly once on the
    quota ledger through the one Invocation terminalization hook and retries
    cannot double-charge;
  - bare prompt strings (maistro-evolve's call shape) normalized to message
    lists; the deployment's `chat_default_model` default is preserved.
- A process with no canonical authority (engine absent, stub agent port, no
  Container) keeps the raw call — the same documented fallback rule the demo
  `LocalTaskBackend` executor follows; that process has no ledger to write to.
- Per the issue's stop condition, this supplies the one canonical effect
  authority; it does not thread an independent recording callback through
  Evolve's runner.

## Evidence

- `test_build_llm_call_crosses_the_engine_bridge_governed_egress` — with a
  started bridge, the llm_call invokes `governed_egress.complete` with the
  Binding/capability/credential scope, normalizes prompts, keeps the default
  model, uses cycle-scoped run identity with per-call attempt/effect
  identity, and raw HTTP is asserted unreachable.
- `test_build_llm_call_stub_port_keeps_the_raw_fallback` — stub port
  (`governed_egress=None`) keeps the raw poster, mirroring the demo task
  backend's documented fallback.
