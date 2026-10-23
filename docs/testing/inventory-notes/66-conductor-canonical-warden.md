---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# #66 Conductor canonical Warden composition

Conductor chat, voice, the HITL agent/config door and the inbound harness
surface reach a Warden through two sites, and each built its own detector:
`services/agent_materialization._warden()` did `Warden()` and
`routes/harness._get_manager()` did `HarnessSessionManager(..., warden=Warden())`.
That is one security guarantee per surface with no shared object behind them —
the shape #1171 names ("route-local bare instances") — and it would keep every
neighbouring surface pattern-only the moment canonical composition gained
layers (the LLM-judge tier) or a different policy version.

`services.engine.process_warden()` is now the single resolution point: the core
Container's composed `warden` when a Container is behind the engine singleton,
a cached process-wide detector when there is none. The missing-Container case
is deliberately a detector rather than a refusal — `get_engine()` raises before
the lifespan boots, and turning a boot-order accident into an unscanned write
is the fail-open this issue exists to remove. `agent_materialization` resolves
per call (so a replaced Container governs the next scan, no restart) and keeps
`_warden_instance` as the test-only override seam the fail-closed tests use;
`routes/harness` resolves once, when it builds its cached manager.

Layer parity (#1171's second bullet) is not claimed here: no composition root in
this tree constructs `Warden(llm=...)` today, so there is no configured judge
for a route-local instance to miss. What changed is identity — one detector per
process — and that is what the tests hold.

New tests: three in `packages/hive-conductor/backend/tests/test_harness_routes.py`
(the lazily built manager takes the Container's detector and constructs none of
its own; an inbound turn is refused over HTTP by that detector; with no
Container the manager still gets a cached real detector) and three in
`packages/hive-conductor/backend/tests/test_agent_materialization.py`
(`scan_config` judges with the Container's detector; a replaced Container lands
on the next scan; with no Container the walk is still scanned by a real Warden),
and one in `packages/hive-conductor/backend/tests/test_chat_voice_gates.py`
(`/v1/chat/complete` is gated by the Container's detector, so the surface #66's
first criterion names inherits the one pipeline instead of getting a second).
