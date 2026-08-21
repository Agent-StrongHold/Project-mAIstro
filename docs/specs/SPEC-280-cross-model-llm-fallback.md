---
id: SPEC-280
title: "Cross-model LLM fallback in the conductor retry loop"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-04
substrate:
  - maistro-engine#ADR-070426-ac56
implements:
  - maistro-engine#ADR-070426-ac56
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
---

# SPEC-280: Cross-model LLM fallback in the conductor retry loop

## Context

ADR-070426-ac56 decides that a retryable conductor LLM-call failure should advance to the next
model in `CostAwareRouter.fallback_chain()` instead of re-trying the same model, and flags the
DI/interface change as the invasive part deferred from implementation in that pass. This SPEC lays
out that interface change concretely — signatures, control flow, exhaustion handling, acceptance
criteria — without implementing it, per the ADR's non-goals.

Today's call chain has no router dependency anywhere:

```
TaskRunner._execute_task()
  → self._executor(request)              # TaskExecutor = Callable[[TaskCreate], Coroutine[..., ConductorOutput]]
      → run_task(task: TaskCreate)        # agents/conductor.py:193
          → resolve_model(tier_config.model)          # config/model_resolver.py — single (model, base_url, use_json_mode) tuple
          → build_conductor(model=resolved_model, base_url=base_url)   # ConductorCall (frozen dataclass)
          → _run_with_retry(call, prompt, tier_config, max_tokens)     # agents/conductor.py:135-189
              → _call_gateway(call, ...)   # same `call` object on every attempt
```

`TaskRunner.__init__` (`tasks/runner.py:34-44`) takes an injected `executor: TaskExecutor` — this
is the existing seam that already exists to avoid `tasks/` ↔ `agents/` coupling; the router
dependency should thread through the same seam rather than adding a new one.

## Goals

- Give `_run_with_retry` (or its replacement) access to a `CostAwareRouter`/`LLMProviderRegistry` so
  a retryable failure can consult `fallback_chain(current_model)` and advance to the next
  candidate, instead of re-issuing the identical `ConductorCall`.
- Keep the change additive to the existing `TaskExecutor` seam (`tasks/runner.py`) — no new global
  singleton, no import of `providers/router.py` from `tasks/`.
- Preserve every existing behavior `_run_with_retry` has today when no router is supplied (backward
  compatible default: same-model retry, unchanged from current behavior) — callers that don't wire
  a router keep today's semantics exactly.
- Define precisely what happens when every candidate in the fallback chain has been tried and
  failed: surface the **original** failing model's last exception, not a new generic message that
  discards which model(s) were actually attempted.

## Non-goals

- Changing the retry backoff/circuit-breaker logic (`llm_circuit`, exponential backoff with
  jitter) — unchanged, per ADR-070426-ac56.
- Changing `CostAwareRouter.select()`'s budget-filtering or latency-sorting behavior.
- Implementing the code — this SPEC is docs-only, same deferral as its parent ADR. A follow-up PR
  implements this design and the associated tests.
- Redesigning `resolve_model()`/`build_conductor()` beyond parameterizing the model name they
  already accept.
- Live model-catalog discovery (rejected in the ADR) — the registry remains the single source of
  truth for what models exist.

## Decision

### 1. Signature changes

`build_conductor()` already accepts `model: str | None` — no change needed there. The new surface
area is entirely about *who supplies which model to try next* and *where that decision is made*.

```python
# providers/protocols.py — already exists, no change
class LLMRouter(Protocol):
    async def fallback_chain(self, name: str) -> list[ModelMetadata]: ...

# agents/conductor.py — new optional parameter, threaded through from run_task
async def _run_with_retry(
    call: ConductorCall,
    prompt: str,
    tier_config: TierConfig,
    max_tokens: int,
    router: LLMRouter | None = None,   # NEW — optional, preserves default behavior when None
) -> ConductorOutput:
    ...

async def run_task(
    task: TaskCreate,
    router: LLMRouter | None = None,   # NEW — optional, defaults to today's single-model behavior
) -> ConductorOutput:
    ...
```

`router: LLMRouter | None = None` keeps `run_task`/`_run_with_retry` callable exactly as today for
any caller that doesn't (yet) supply one — this is what makes the change additive rather than a
breaking signature change to every existing call site.

`TaskRunner` gains the same optional parameter, threaded to the executor via a partial/closure at
construction time rather than a per-task argument (the `TaskExecutor` callable type,
`Callable[[TaskCreate], Coroutine[Any, Any, ConductorOutput]]`, does not change — whatever
constructs the executor closes over the router):

```python
# tasks/runner.py — TaskExecutor type is UNCHANGED; the router is bound at construction time
def make_conductor_executor(router: LLMRouter | None = None) -> TaskExecutor:
    async def _executor(task: TaskCreate) -> ConductorOutput:
        return await run_task(task, router=router)
    return _executor

runner = TaskRunner(queue=queue, executor=make_conductor_executor(router=my_router))
```

This keeps `TaskRunner` itself completely unaware of routers/models — it only ever knows
`TaskExecutor`, preserving the decoupling comment already in `runner.py:29-31` ("breaking the
bidirectional coupling between tasks/ and agents/ packages").

### 2. Retry-loop pseudocode

```python
async def _run_with_retry(call, prompt, tier_config, max_tokens, router=None):
    if not llm_circuit.allow_request():
        raise CircuitOpenError(llm_circuit)

    # Resolve the candidate chain up front. Without a router, the chain is just
    # the one model already resolved into `call` — behavior identical to today.
    candidates: list[ConductorCall] = [call]
    if router is not None:
        chain = await router.fallback_chain(call.model)
        candidates = [
            build_conductor(model=m.name, base_url=call.base_url)
            for m in chain
            if m.name == call.model or router_registry_is_available(m.name)
        ] or [call]  # never end up with an empty candidate list

    last_exc: Exception | None = None
    first_model = candidates[0].model

    for candidate in candidates:
        for attempt in range(tier_config.max_llm_retries):
            try:
                llm_requests_total.inc()
                raw = await asyncio.wait_for(
                    _call_gateway(candidate, prompt, max_tokens, tier_config.timeout),
                    timeout=tier_config.timeout,
                )
                result = _parse_json_output(raw)
                llm_circuit.record_success()
                return result
            except TimeoutError as exc:
                last_exc = exc
                await logger.awarning("llm_timeout", model=candidate.model, attempt=attempt + 1, ...)
            except Exception as exc:
                if _is_retryable(exc):
                    last_exc = exc
                    await logger.awarning("llm_transient_error", model=candidate.model, attempt=attempt + 1, ...)
                else:
                    llm_circuit.record_failure()
                    llm_errors_total.inc(error_type="non_retryable")
                    raise

            llm_circuit.record_failure()
            llm_errors_total.inc(error_type="retryable")

            if attempt < tier_config.max_llm_retries - 1:
                delay = tier_config.initial_backoff * (2**attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
        # exhausted this candidate's retries — advance to the next candidate, if any

    # Every candidate in the chain exhausted its retries.
    raise LLMProviderError(
        f"LLM call failed after exhausting fallback chain starting at {first_model!r} "
        f"({len(candidates)} candidate(s) tried): {last_exc}"
    )
```

Key structural decisions embedded in the pseudocode:

- **Retry budget is per-candidate, not shared across the whole chain.** Each model in the chain
  gets its own full `tier_config.max_llm_retries` attempts before falling through to the next
  candidate. (Open question below: should the budget instead be split across the whole chain? See
  Open Questions.)
- **The fallback chain is resolved once, up front**, not re-queried after each failure — matching
  `CostAwareRouter.select()`'s own pattern of resolving `fallback_chain()` once per selection
  (`router.py:39-45`) rather than per-retry-attempt.
- **Availability is checked when building the candidate list**, not inside the retry loop —
  unavailable models (per `LLMProviderRegistry.is_available()`) are skipped entirely rather than
  attempted and immediately failed, avoiding a wasted `_call_gateway` round-trip against a model the
  registry already knows is circuit-broken.
- **A model that appears twice in a chain (duplicate/cycle) is never retried twice** —
  `fallback_chain()` itself already dedupes (`router.py:74-76`'s `seen` set), so this is inherited
  for free, not re-implemented here.

### 3. Model exhaustion handling

When every candidate's retry budget is exhausted, the raised `LLMProviderError` must:

- Reference the **first** (originally resolved) model by name, not the last-tried fallback — the
  caller's mental model is "I asked for X and it failed," and losing that in favor of "Z (the third
  fallback) failed" would make the error harder to act on.
- Report **how many candidates were tried**, so an operator can distinguish "one model failed
  4 times" from "four different models each failed once" at a glance from the error message alone.
- Preserve `last_exc` (the most recent underlying exception) in the message, exactly as today's
  `LLMProviderError(f"LLM call failed after {tier_config.max_llm_retries} retries: {last_exc}")`
  does — this SPEC does not remove that diagnostic, only extends the surrounding message.

## Acceptance criteria

- **AC-1**: `run_task(task)` (no `router` argument) behaves identically to today's implementation —
  same model retried `tier_config.max_llm_retries` times, same backoff, same exception on
  exhaustion (modulo the widened message text, which must still contain the original error).
- **AC-2**: `run_task(task, router=router)` where the first candidate succeeds on the first attempt
  never consults `router.fallback_chain()` for a *second* time and never builds a second
  `ConductorCall` — the common case (no failures) has zero behavioral or performance overhead
  beyond the one `fallback_chain()` call needed to build the candidate list.
- **AC-3**: A retryable failure (429/5xx/timeout/connect-error) on the first candidate, with a
  healthy second candidate in the fallback chain, results in the second candidate's model being
  called next — not a same-model retry of the first candidate beyond its own budget.
- **AC-4**: A non-retryable exception on any candidate raises immediately without consulting or
  advancing the fallback chain — matches today's `else: raise` branch (`conductor.py:174-177`)
  exactly, unchanged for any candidate position.
- **AC-5**: When every candidate in the resolved chain exhausts its retry budget, the raised
  `LLMProviderError` message contains: the original (first) model's name, the count of candidates
  tried, and the last underlying exception's string representation.
- **AC-6**: A model present in the fallback chain but reported `is_available() == False` by the
  registry is excluded from the candidate list entirely — it is never attempted, and no
  `_call_gateway` call is made against it.
- **AC-7**: A fallback chain containing a cycle or a duplicate model name (per
  `CostAwareRouter.fallback_chain()`'s own dedup) never causes the same `ConductorCall` to be built
  or attempted twice.
- **AC-8**: `TaskRunner`'s public interface (`__init__`, `start`, `stop`, `drain`) is unchanged —
  the router is bound into the injected `TaskExecutor` closure at construction time, never passed
  as a new `TaskRunner` constructor parameter or a per-task argument.
- **AC-9**: Structured log lines emitted during a retry (`llm_timeout`, `llm_transient_error`)
  include a `model=` field identifying which candidate was being attempted, so a chain with
  multiple candidates produces distinguishable log entries per model.
- **AC-10**: `llm_circuit`'s success/failure recording and `allow_request()` gating are called
  exactly as many times as today's implementation would for an equivalent number of total attempts
  — i.e. the circuit breaker's semantics (tracking overall LLM-call health) are unaffected by
  whether those attempts targeted one model or several.

## Testing

Stronghold's `tests/api/test_litellm_client.py` (15+ tests, covering the phase-1/phase-2 fallback
search it implements) is the closest existing coverage for the *behavior* this SPEC ports the
underlying primitive for — the assertions below carry forward its intent, adapted to the
registry-based `fallback_chain()` design instead of live discovery:

- **No-router backward compatibility**: `run_task(task)` without a router reproduces today's
  existing conductor test suite unchanged (AC-1) — this is a regression gate, not new coverage.
- **First-candidate success**: fake `LLMRouter` returning a single-element chain; assert exactly
  one `_call_gateway` invocation and no extra `fallback_chain()` calls beyond the first (AC-2).
- **Fallback on retryable failure**: fake gateway that fails with a `429`-equivalent on the first
  candidate's every attempt and succeeds on the second candidate's first attempt; assert the
  second candidate's model appears in the successful result's provenance and that the first
  candidate was attempted exactly `max_llm_retries` times before advancing (AC-3, mirrors
  stronghold's "second model succeeds after first exhausts retries" case).
- **Non-retryable short-circuit**: fake gateway raising a non-retryable error (e.g. a `400`) on the
  first candidate; assert no second candidate is attempted and the exception propagates unchanged
  (AC-4).
- **Full-chain exhaustion**: fake gateway that fails every attempt on every candidate; assert the
  raised `LLMProviderError` names the first model, reports the correct candidate count, and
  preserves the last exception's text (AC-5, mirrors stronghold's "all models exhausted" test).
- **Unavailable-model exclusion**: fake registry reporting one chain member unavailable; assert it
  is never attempted and never appears in candidate-count accounting (AC-6, mirrors stronghold's
  availability-filtering tests).
- **Cycle/duplicate safety**: fake router returning a chain with a self-referential
  `fallback_to`; assert no duplicate `ConductorCall` attempts (AC-7) — this is largely inherited
  from `CostAwareRouter.fallback_chain()`'s own existing dedup tests, but needs a conductor-level
  test proving the retry loop doesn't re-introduce a duplicate via its own candidate-building step.
- **`TaskRunner` interface stability**: existing `TaskRunner` tests continue to pass unmodified
  (AC-8) — a new test constructs a `TaskRunner` with a router-bound executor closure and asserts no
  change to `TaskRunner`'s own public methods or behavior.
- **Structured logging**: a retry across two candidates produces two distinguishable log entries,
  each with the correct `model=` value (AC-9).
- **Circuit breaker call counts**: parametrized test comparing `llm_circuit.record_success`/
  `record_failure` call counts between a single-model N-attempt run and an equivalent
  multi-candidate run with the same total attempt count (AC-10).

## Open questions

- Should the retry budget (`tier_config.max_llm_retries`) be **per-candidate** (this SPEC's default
  design — each model gets a full retry budget) or **shared across the whole chain** (total
  attempts capped at `max_llm_retries` regardless of how many models are tried)? Per-candidate is
  simpler to reason about and matches "give each model a fair chance," but could multiply total
  latency by the chain length in a worst-case all-models-down scenario. The implementing PR should
  decide based on the tier's timeout budget and get sign-off before implementation, not default
  silently to one or the other.
- Should `fallback_chain()`'s resolved candidates be re-filtered against the *original* task's
  `RouterBudget` (cost/latency/reasoning constraints), the way `CostAwareRouter.select()` does via
  `_satisfies()`? Today's `fallback_chain()` does not filter by budget — a fallback model that is
  technically "available" but violates the original request's cost ceiling could be picked. This
  SPEC's pseudocode above does not filter by budget; the implementing PR should confirm whether
  that's acceptable for the conductor's use case (which does not currently pass a `RouterBudget`
  at all) or whether one needs to be threaded through from `TierConfig`.
- Where does the `LLMProviderRegistry`/`CostAwareRouter` instance actually get constructed and
  wired to `TaskRunner` in production (vs. in tests, where a fake is trivial to construct)? This
  SPEC defines the shape of the dependency but not its concrete production wiring (e.g. which
  container/DI entry point owns constructing the registry from settings) — that's implementation
  work for the following PR, informed by how `container.py` already wires comparable dependencies
  elsewhere in the engine.

## References

- [ADR-070426-ac56: Wire CostAwareRouter.fallback_chain() into the conductor's retry loop](../adr/ADR-070426-ac56-cross-model-llm-fallback.md)
- [ADR-079: Model registry and routing (embeddings)](../adr/ADR-079-model-registry-routing-embeddings.md)
- [ADR-038: Reliability taxonomy](../adr/ADR-038-reliability-taxonomy.md)
- Seams: `packages/maistro-core/src/maistro/agents/conductor.py` (`_run_with_retry`,
  `_call_gateway`, `build_conductor`, `run_task`), `packages/maistro-core/src/maistro/tasks/runner.py`
  (`TaskRunner`, `TaskExecutor`), `packages/maistro-core/src/maistro/providers/router.py`
  (`CostAwareRouter`), `packages/maistro-core/src/maistro/providers/protocols.py` (`LLMRouter`,
  `LLMProviderRegistry`), `packages/maistro-core/src/maistro/providers/types.py` (`ModelMetadata`,
  `RouterBudget`)
- Prior art (not ported as-is, see parent ADR's Alternatives): `stronghold/src/stronghold/api/litellm_client.py`
  (`LiteLLMClient.complete`), `stronghold/tests/api/test_litellm_client.py`
