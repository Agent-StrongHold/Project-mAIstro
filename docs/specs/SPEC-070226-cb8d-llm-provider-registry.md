---
id: SPEC-070226-cb8d
title: "LLM provider / model registry, routing, and embeddings"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-07-02
substrate:
  - maistro-engine#ADR-079
  - maistro-engine#ADR-085
  - maistro-engine#SPEC-014
implements:
  - maistro-engine#ADR-079
related:
  - maistro-engine#ADR-094
  - maistro-engine#SPEC-270
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/providers/test_registry.py
  - packages/maistro-core/tests/providers/test_router.py
  - packages/maistro-core/tests/providers/test_cost.py
  - packages/maistro-core/tests/providers/test_config.py
layer: Tools
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-cb8d: LLM provider / model registry, routing, and embeddings

## Context

Agents currently call the OpenAI-compatible gateway directly. ADR-079 specifies a unified provider
registry where operators declare available models (claude-3-opus, gpt-4-turbo, local-llama, etc.),
each with cost/latency/tier metadata, and a router that selects the best model for each call
based on task requirements (reasoning depth, latency budget, cost constraint).

## Goals

- Single source of truth for available LLM providers and models (registry).
- Per-model cost/latency/capability metadata (used by router + quota tracking per ADR-085).
- Router selects model based on task type, cost budget, reasoning requirements.
- Embedding models (vector generation) registry and routing.
- Fallback chain (if primary model unavailable, try secondary).

## Non-goals

- Fine-tuning model selection (ADR-079 follow-up).
- Multi-cloud vendor negotiation (Stronghold).

## Decision

### Provider registry structure

Implemented in `packages/maistro-core/src/maistro/providers/`.

```python
@dataclass(frozen=True)
class ModelMetadata:
    name: str  # "claude-3-opus", "gpt-4-turbo"
    provider: str  # "anthropic", "openai", "local"
    cost_per_1k_input: float  # cents
    cost_per_1k_output: float  # cents
    latency_p50_ms: int
    tier: Literal["fast", "balanced", "powerful"] = "balanced"
    reasoning_capable: bool = False
    max_tokens: int = 4096
    fallback_to: tuple[str, ...] = ()  # ("gpt-4-turbo", ...) — immutable

@dataclass(frozen=True)
class EmbeddingModelMetadata:
    name: str  # "text-embedding-ada-002"
    provider: str
    dimension: int
    cost_per_1k_tokens: float  # cents
    max_input_tokens: int = 8192

@dataclass(frozen=True)
class RouterBudget:
    """Typed budget (replaces the untyped budget dict of the original draft)."""
    max_cost_cents: float | None = None
    max_latency_ms: int | None = None
    reasoning: bool = False

@dataclass(frozen=True)
class RoutingTask:
    """Minimal task descriptor (core has no plain Task dataclass)."""
    task_type: str = "general"
    description: str = ""

class LLMProviderRegistry(Protocol):
    async def list_models(self, filter_by: dict[str, str] | None = None) -> list[ModelMetadata]:
        """List available models, optionally filtered by provider/tier/name."""

    async def get_model(self, name: str) -> ModelMetadata:
        """Fetch a specific model's metadata. Raises ModelNotFoundError."""

    async def list_embedding_models(self) -> list[EmbeddingModelMetadata]: ...

    async def get_embedding_model(self, name: str) -> EmbeddingModelMetadata: ...

    def is_available(self, name: str) -> bool:
        """Availability flag (set by circuit-breaking per ADR-038)."""

class LLMRouter(Protocol):
    async def select(self, task: RoutingTask, budget: RouterBudget | None = None) -> ModelMetadata:
        """Select the best available model for the task under the budget."""

    async def select_embedding(self, input_size_tokens: int) -> EmbeddingModelMetadata: ...

    async def fallback_chain(self, name: str) -> list[ModelMetadata]:
        """Ordered fallback chain starting at a model (inclusive); cycle-safe."""
```

The concrete registry is `InMemoryProviderRegistry` (registration-order-preserving,
re-registration replaces, `mark_unavailable`/`mark_available` for ADR-038 integration).

### Default config (INI-style or YAML)

```yaml
models:
  - name: claude-3-opus
    provider: anthropic
    tier: powerful
    cost_input: 0.15
    cost_output: 0.75
    latency_p50_ms: 800
    reasoning: true
    fallback: [gpt-4-turbo]
  
  - name: gpt-4-turbo
    provider: openai
    tier: powerful
    cost_input: 0.03
    cost_output: 0.06
    latency_p50_ms: 1200
    reasoning: false
    fallback: [gpt-3.5-turbo]

embeddings:
  - name: text-embedding-ada-002
    provider: openai
    dimension: 1536
    cost_per_1k: 0.0001
```

### Router logic

`CostAwareRouter` (in `maistro/providers/router.py`):

1. Filter all registered models by the budget (cost per 1k input, latency p50,
   reasoning requirement). If none match, raise `NoEligibleModelError`.
2. Order candidates by latency (fastest first).
3. For each candidate, walk its fallback chain (breadth-first over `fallback_to`,
   cycle-safe, dangling names skipped) and return the first model that both
   satisfies the budget and is currently available per the registry.
4. If every eligible model is unavailable, raise `NoEligibleModelError`.

`select_embedding(input_size_tokens)` picks the cheapest available embedding model
whose `max_input_tokens` fits the input; raises `NoEligibleModelError` if none fits.

Unknown model names (in `get_model`, `get_embedding_model`, `mark_unavailable`, or a
`fallback_chain` root) raise `ModelNotFoundError` — never a silent fallback.

### Integration with quota tracking (ADR-085)

```python
# When a task calls an LLM via the router:
model = await router.select(task, budget)
response = await llm_client.call(model=model.name, ...)

# Cost comes from the pure helper (no hardcoded pricing, quota package untouched):
from maistro.providers import compute_cost_cents

cost_cents = compute_cost_cents(model, response.input_tokens, response.output_tokens)
quota_tracker.record_usage(
    provider=model.provider,
    billing_cycle=cycle,
    input_tokens=response.input_tokens,
    output_tokens=response.output_tokens,
)
```

`compute_embedding_cost_cents(model, input_tokens)` is the embedding analogue.
Config loading: `load_provider_config(path)` parses/validates the YAML above
(raising `ProviderConfigError` on malformed input) and
`load_provider_registry(path)` returns a populated `InMemoryProviderRegistry`.

## Acceptance criteria

- [ ] LLMProviderRegistry.list_models() returns all configured models (property: ordering
      is consistent; no duplicates).
- [ ] Router selects a model that satisfies the budget constraints (cost, latency, reasoning).
- [ ] Router falls back to next in chain if primary is unavailable (circuit breaker test).
- [ ] Embedding model selection works independently (separate registry + router).
- [ ] Cost tracking in quota system uses registry metadata (no hardcoded pricing).
- [ ] Unknown model name raises ModelNotFoundError (not silent fallback).

## Testing

- Unit: router selection with various budgets (cheap+fast vs. powerful vs. reasoning).
- Integration: a task specifies budget, router picks correct model, quota tracker logs correct cost.
- Fallback chain: mark primary unavailable, confirm router tries secondary.
- Property: router selection always respects all constraints (no over-budget).

## Open questions

- Should the registry be hot-reloadable (operators update config without restart)? (Defer to Phase 2.)
- Multi-cloud provider failover (detect one provider is down, switch to another)? (Defer to Phase 2.)

## References

- [ADR-079: LLM Provider Registry](../adr/ADR-079-model-registry-routing-embeddings.md)
- [ADR-085: Cost, Quota, Rate Limiting](../adr/ADR-085-cost-quota-rate-limiting.md)
