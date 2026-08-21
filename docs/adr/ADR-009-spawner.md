---
id: ADR-009
title: Spawner pattern
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-004
  - maistro-engine#ADR-005
  - maistro-engine#ADR-006
  - maistro-engine#ADR-007
  - maistro-engine#ADR-008
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-009: Spawner pattern

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T1  
**Depends on:** ADR-004, ADR-005, ADR-006, ADR-007, ADR-008

---

## Context

The conductor currently calls `run_task()` directly with raw strings. There is no single entry point for agent execution that handles prompt assembly, variant selection, schema injection, Langfuse tracing, typed parsing, and error categorization uniformly.

## Decision

Port `Spawner` into `src/maistro/agents/spawner/spawner.py`. Key adaptation: in maistro-engine there is no separate HTTP gateway process — LLM calls go through `LiteLLM` via the existing `config/model_resolver.py`. So `Spawner` accepts an injected `LLMCaller` protocol rather than a gateway URL.

Inter-agent injection screening (`_upstream_output_is_suspicious`, `_sanitize_upstream`) is ported inline. These will be superseded by the Warden (T3) but protect upstream output integrity for T1.

## Interface

```python
# Protocol — injected; default impl wraps LiteLLM
class LLMCaller(Protocol):
    async def call(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        tier: int,
        lane: str,
    ) -> dict[str, Any]: ...  # {"content": str, "model": str, "usage": dict}

class Spawner:
    def __init__(
        self,
        llm_caller: LLMCaller,
        prompt_manager=None,       # optional
        langfuse_tracer=None,      # optional — uses existing trace_agent decorator
        variant_selector=None,     # optional VariantSelector
        recipe_registry=None,      # optional RecipeRegistry
    ) -> None: ...

    async def spawn(self, spec: AgentSpec) -> AgentOutput: ...
    async def close(self) -> None: ...
```

`spawn()` pipeline:
1. `spec.with_defaults()`
2. Recipe lookup → variant selection → fill `spec.prompt_label`, `spec.result_type`, `spec.temperature`
3. Resolve `result_type` via `resolve_schema`
4. Build pre-output `AgentOutput` envelope
5. Create Langfuse span (if tracer + trace_id present)
6. Assemble prompts: context layers + upstream screening + role prompt
7. `inject_schema` if typed output expected
8. Call `llm_caller.call(...)`
9. `parse` typed output; fall back to `_try_parse_json`
10. `mark_complete()` + close Langfuse span
11. Categorize exceptions → `mark_error(error, ErrorType)`

## Acceptance criteria

- [ ] `spawn()` with minimal spec returns a successful `AgentOutput`
- [ ] `spawn()` sets `variant_used` from variant selector when recipe has multiple variants
- [ ] `spawn()` injects schema into system prompt when `result_type` is set
- [ ] `spawn()` sets `output_parsed` when typed output parses successfully
- [ ] `spawn()` marks `recoverable=False` on `SAFETY_VIOLATION`
- [ ] `spawn()` marks `recoverable=True` on `TIMEOUT`
- [ ] `spawn()` sanitizes upstream output containing injection pattern before prompt assembly
- [ ] LLM timeout → `AgentOutput.error_type == ErrorType.TIMEOUT`
- [ ] `spawn()` works with all optional deps set to `None`

## Test plan

| Test | Covers |
|---|---|
| `test_spawn_minimal_success` | happy path, fake LLM |
| `test_spawn_sets_variant_from_selector` | variant selection integration |
| `test_spawn_injects_schema` | result_type → schema in prompt |
| `test_spawn_parses_typed_output` | structured parse |
| `test_spawn_timeout_categorized` | TIMEOUT error type |
| `test_spawn_upstream_injection_sanitized` | inter-agent screening |
| `test_spawn_no_optional_deps` | all None optional deps |
| `test_spawn_mark_complete_called` | duration_ms > 0 |

## Out of scope

Ultra Think (`parallel_generations > 1`, T9). Multi-model fan-out (T9). ExemplarLibrary injection (T9+). Gateway HTTP (replaced by injected LLMCaller).

## Source references

- `Project_mAIstro/conductor/orchestrator/agents/spawner.py`
- `Project_mAIstro/conductor/orchestrator/agents/structured_output.py`
