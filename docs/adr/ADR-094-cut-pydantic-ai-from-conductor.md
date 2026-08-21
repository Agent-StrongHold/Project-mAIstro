---
id: ADR-094
title: Cut pydantic-ai from the conductor — call the OpenAI-compatible gateway directly
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-01
substrate:
  - maistro-engine#ADR-019
implements: []
related:
  - maistro-engine#ADR-058
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
    date: 2026-06-01
  - status: Accepted
    date: 2026-06-01
---

# ADR-094: Cut pydantic-ai from the conductor

## Context

`pydantic-ai` was a declared dependency used in exactly one module
(`maistro/agents/conductor.py`) as a thin wrapper: it built a `pydantic_ai.Agent`
over an `OpenAIChatModel`/`OpenAIProvider` pointed at the LiteLLM gateway, ran one call,
and returned structured output. The conductor already carried a hand-rolled JSON-mode
fallback (prompt for JSON → `ConductorOutput.model_validate`) for models without tool
schemas — i.e. ~80% of pydantic-ai's value was already reimplemented.

Meanwhile the engine has a full in-house agent stack (`agents/`, `orchestrator/`,
`graph/`, `maistro-evolve`) that pydantic-ai overlaps. Using a full agent framework in
one file as a thin OpenAI wrapper is the worst trade: 100% of the dependency weight for
~20% of the value. pydantic-ai also pulled a large transitive tree (anthropic, cohere,
boto3/botocore, ag-ui-protocol, …) and shipped GHSA-cqp8-fcvh-x7r3 (CVSS 6.8).

## Decision

**Cut pydantic-ai.** The conductor calls the OpenAI-compatible LiteLLM gateway directly
over HTTP (`httpx` POST to `/chat/completions` with `response_format: json_object`) and
validates the response into `ConductorOutput` with pydantic — promoting the former
JSON-mode fallback to the only path. The differentiation lives in our own runtime
(graph/orchestrator/evolve), so a thin gateway client is sufficient and the second agent
runtime is removed.

`run_task(task) -> ConductorOutput` is unchanged (the public surface used by the server,
hive-conductor engine, and tests); only the internals changed. Circuit breaker, retry,
backoff, metrics, and tracing are preserved.

## Consequences

### Positive
- Removes pydantic-ai + its provider-SDK tree from the lock; clears GHSA-cqp8-fcvh-x7r3.
- One agent runtime (ours), not two; smaller image; less to maintain.
- The gateway call is explicit and debuggable.

### Negative / Trade-offs
- We forgo pydantic-ai's built-in tool-calling loop and native OTel instrumentation. If a
  future need for first-class multi-step tool orchestration appears, revisit (the
  "commit" alternative — adopt pydantic-ai wholesale and retire overlapping in-house code).
- Structured output now depends on the model honoring `response_format: json_object`;
  parse/validation failures are treated as retryable.

### Neutral
- The LiteLLM **proxy** is unaffected (it runs as its own container; we only call it).

## Source references
- `packages/maistro-core/src/maistro/agents/conductor.py` — the rewrite.
- ADR-058 (sandbox isolation), SPEC-190 (sandbox substrate) — adjacent agent-runtime work.
