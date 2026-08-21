---
id: ADR-070426-ac56
title: Wire CostAwareRouter.fallback_chain() into the conductor's retry loop
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#ADR-079
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-07-04
---

# ADR-070426-ac56: Wire CostAwareRouter.fallback_chain() into the conductor's retry loop

## Context

The repo-mining sweep of `stronghold` flagged that its `LiteLLMClient.complete` implements
live-discovered, heavily-tested cross-model fallback on retryable failures, while the engine's
conductor retries the *same* model on every attempt. Concretely:

- `packages/maistro-core/src/maistro/agents/conductor.py::_run_with_retry` (lines ~135-189) retries
  up to `tier_config.max_llm_retries` times against a single `ConductorCall` built once by
  `build_conductor(model=resolved_model, base_url=base_url)` at `run_task`'s call site (line 240).
  `_is_retryable()` (lines 117-126) already classifies timeouts, connect errors, and
  `429`/`502`/`503`/`504` (`_RETRYABLE_STATUS_CODES`, line 37) as worth retrying — but every retry
  in the loop (lines 147-185) calls `_call_gateway(call, ...)` with the *same* `call.model*, so a
  model-side outage or rate limit is retried against the identical model with exponential backoff,
  never routed to an alternative.
- `packages/maistro-core/src/maistro/providers/router.py::CostAwareRouter` already has the primitive
  this needs: `fallback_chain()` (lines 62-87) resolves the ordered fallback chain for a model name
  by breadth-first traversal of each `ModelMetadata.fallback_to`, skipping cycles/duplicates/dangling
  names, and `select()` (lines 26-46) already consumes it — trying each candidate's own fallback
  chain in turn until one satisfies the budget and is available
  (`self._registry.is_available(model.name)`, line 44) — but only `select()` calls it. The
  conductor's retry loop is a separate, older code path that never touches `CostAwareRouter` at all.
- Stronghold's own implementation — a live `GET /v1/models` discovery call against the LiteLLM
  proxy, feeding a phase-1 (same-tier) / phase-2 (any-tier) fallback search, backed by 15+ tests in
  `tests/api/test_litellm_client.py` — is **not** the primitive to port forward. The engine already
  has a strictly better one: `CostAwareRouter` operates over a registry-driven, typed
  `ModelMetadata` catalog with declared `fallback_to` chains and `is_available()` state, instead of
  re-discovering the model list from a live HTTP call on every failure. Porting stronghold's
  live-fetch-everything approach would be regressive given the registry-based router already exists
  and is the more testable, less network-chatty design.

## Decision

Wire `CostAwareRouter.fallback_chain()` into `_run_with_retry`'s retry loop so a retryable failure
(429/5xx/timeout/connect-error) advances to the **next model candidate** in the resolved model's
fallback chain, instead of re-trying the same model with backoff alone:

- On each retryable failure, instead of re-issuing `_call_gateway(call, ...)` with the same `call`,
  consult the router's `fallback_chain(current_model_name)` and advance to the next untried
  candidate that `is_available()`.
- For each new candidate, rebuild the `ConductorCall` via
  `build_conductor(model=next_candidate.name, base_url=...)` — the call object is already a frozen
  dataclass rebuilt fresh per attempt today (it's constructed once in `run_task` and passed down),
  so rebuilding it per-candidate is a natural extension of the existing shape, not a new pattern.
- Preserve the existing exponential-backoff-with-jitter delay (lines 182-185) between attempts —
  this ADR widens *what* a retry attempt targets, not the backoff timing itself.
- Preserve the existing circuit-breaker interaction (`llm_circuit.allow_request()` /
  `record_success()` / `record_failure()`) — the breaker tracks the conductor's overall LLM-call
  health, not per-model health; that stays as-is.
- Non-retryable exceptions still raise immediately without consulting the fallback chain (line
  174-177's `else` branch is unchanged).

**This requires threading a `CostAwareRouter` (or, more precisely, its backing
`LLMProviderRegistry`) dependency through `TaskRunner`/`run_task`, which today resolves a single,
fixed model string via `resolve_model()` (`conductor.py:228`) and has no registry/router
dependency anywhere in its call chain.** This is the invasive part flagged for deferral to
docs-only in this pass: it is an actual dependency-injection/interface change to `run_task`'s
signature and whatever constructs `TaskRunner`, not a localized swap inside
`_run_with_retry`. `_run_with_retry` cannot call `fallback_chain()` without first having a
`CostAwareRouter` instance available to it, and today nothing in the conductor's call chain
constructs, receives, or wires one. **SPEC-070426-... (companion SPEC, see References) lays out the
concrete interface change and acceptance criteria without implementing it.**

## Alternatives considered

**Status quo — retry the same model, rely on backoff alone.** Rejected as the thing this ADR
exists to fix: a sustained provider-side outage or hard rate limit on one model exhausts all
`max_llm_retries` attempts against a single unavailable target, when a fallback model may be
healthy the entire time. This is exactly the gap stronghold's tests demonstrate is worth closing.

**Live `/v1/models` discovery per failure, mirroring stronghold's `LiteLLMClient.complete`.**
Rejected: redundant given the engine's registry-driven catalog already exists and already declares
`fallback_to` chains and availability state (`ModelMetadata`, `LLMProviderRegistry.is_available()`).
Re-discovering the model list from a live HTTP call on every failure adds a network round-trip
and a second source of truth about which models exist, when the registry the conductor could
already be wired to already answers that question synchronously. The registry-based
`fallback_chain()` primitive is the better foundation precisely because it doesn't require a live
call to find out what to try next.

**Have `_run_with_retry` call `CostAwareRouter.select()` directly instead of `fallback_chain()`.**
Considered but not chosen for the SPEC to design around: `select()` re-applies the full budget
filter (`_satisfies()`, cost/latency/reasoning constraints) and re-sorts by latency on every call,
which is the right shape for *initial* model selection but heavier than what a retry loop needs —
a retry already has a specific failing model in hand and wants "what's next in *this* model's
declared chain," which is exactly `fallback_chain()`'s contract. The SPEC should consider whether
`_satisfies()` still needs to be checked per fallback candidate against the task's original budget,
since `fallback_chain()` itself doesn't filter by budget the way `select()` does.

## Consequences

### Positive
- Retryable failures against one model no longer exhaust the retry budget against a target that
  may be down for the retry window's entire duration — a healthy fallback model can serve the
  request instead.
- Builds on a primitive (`CostAwareRouter.fallback_chain()`) that already exists and is not
  currently dead code from the conductor's perspective — this closes the gap between `select()`
  using it and the retry loop not.
- Explicitly rejects re-implementing stronghold's live-discovery approach, keeping the registry as
  the single source of truth for model catalog + availability.

### Negative / Trade-offs
- Requires a DI/interface change to `run_task`/`TaskRunner` — whatever constructs `TaskRunner` (or
  calls `run_task` directly) must now also supply a `CostAwareRouter`/registry, which today it does
  not. This is real integration work, not a drop-in.
- A request that exhausts every candidate in the fallback chain must still fail with a clear error
  — the SPEC needs to define this precisely (surface the *original* failing model's error, not a
  generic "all models failed" message that loses the root cause) since todays's
  `LLMProviderError(f"LLM call failed after {tier_config.max_llm_retries} retries: {last_exc}")`
  message (line 187-189) assumes a single model throughout.
- Widens the failure surface engineers need to reason about when debugging (which model actually
  served, or failed to serve, a given task) — needs corresponding structured logging (the existing
  `logger.awarning("llm_transient_error", ...)` calls at lines 168-173 already log per-attempt; they
  need a `model=` field added once attempts can target different models).

### Neutral
- Does not touch the retry backoff/circuit-breaker logic already in place (explicit non-goal
  below) — only widens what a retry attempt targets.
- `CostAwareRouter.select()` and its budget-filtering behavior are unchanged; this ADR only adds a
  second consumer of `fallback_chain()`.

## Non-goals

- **Implementing the code.** This ADR is docs-only, per the Wave-2 deferral decision. No change to
  `conductor.py`, `router.py`, `run_task`, or `TaskRunner` ships with this record.
- Changing the retry backoff schedule or circuit-breaker state machine (`llm_circuit`) — both stay
  exactly as they are; only the *target* of a retry attempt changes.
- Redesigning `CostAwareRouter.select()`'s budget-filtering or latency-sorting behavior.
- Porting stronghold's live `/v1/models` discovery — explicitly rejected above.

## References

- [ADR-038: Reliability taxonomy](ADR-038-reliability-taxonomy.md)
- [ADR-079: Model registry and routing (embeddings)](ADR-079-model-registry-routing-embeddings.md)
- Companion SPEC: [SPEC-280: Cross-model LLM fallback in the conductor retry loop](../specs/SPEC-280-cross-model-llm-fallback.md)
- Seams: `packages/maistro-core/src/maistro/agents/conductor.py` (`_run_with_retry` lines 135-189,
  `_call_gateway` lines 91-114, `build_conductor` lines 71-88, `run_task` lines 193-249),
  `packages/maistro-core/src/maistro/providers/router.py`
  (`CostAwareRouter.select`/`fallback_chain` lines 26-87)
- Prior art (not ported, see Alternatives): `stronghold/src/stronghold/api/litellm_client.py`
  (`LiteLLMClient.complete`), `stronghold/tests/api/test_litellm_client.py`
