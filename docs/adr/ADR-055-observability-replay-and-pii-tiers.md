---
id: ADR-055
title: Observability extensions — recorded-response replay and PII sensitivity tiers
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-13
substrate:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-050
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-049
  - maistro-engine#ADR-053
  - maistro-engine#ADR-056
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Observability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
---

# ADR-055: Observability extensions — recorded-response replay and PII sensitivity tiers

## Context

ADR-037 defines traces / metrics / logs / events as the four observability primitives, with required spans, metrics, and event topics. Two gaps it does not address:

1. **Replay.** Trace data is read by humans; the orchestration code path cannot be deterministically re-executed against a recorded trace. Orchestration bugs (wave merge logic per ADR-052, approval gating per ADR-051, memory promotion per ADR-057) can only be debugged by reading traces, never by re-running orchestration against known inputs.
2. **PII handling.** Tool args, LLM prompts, and LLM responses contain user PII, secrets, and high-stakes content. ADR-037 emits all events into one event store with one retention regime. A regulated tenant has nowhere to route sensitive content with stricter handling.

This ADR extends ADR-037 with both.

## Problem

No replay capability for orchestration debugging; no sensitivity-tier routing for PII / secret content.

## Decision

### Recorded-response replay

Substrate-owned proxies sit between agents and the world:

- **LLM client proxy** — records prompt + response into the narrow event log (ADR-037 `events`). Carries the trace/span id from the active trace.
- **Tool dispatcher proxy** — records args + result for every tool call. Same trace/span id linkage.

Replay re-runs orchestration code against recorded responses. The LLM is not re-invoked; tools are not re-invoked. Replay is bounded to **orchestration bug debugging** — wave merge, approval gating, memory promotion, recipe overlay rendering, crash recovery (ADR-056). It does **not** debug prompt/model bugs (that would require deterministic re-execution with temperature-0 LLM + frozen RNG; out of scope here).

The substrate-owned proxy is **non-optional**. Every tool call and every LLM call flows through it. Direct invocation of `litellm`, `fastmcp`, or in-process tool callables that bypass the proxy fail at agent-registration time. This is the single largest architectural commitment in this ADR — but without it, replay is impossible.

### Sensitivity tiers

Three tags. Declared at tool registration (extends ADR-050) and at recipe level (for LLM prompts/responses) via overlay-mergeable field (`merge: replace` per ADR-053):

| Tier | Behaviour | Default retention |
|---|---|---|
| `normal` | Standard event log per ADR-037 | Events indefinite, logs 7d, metrics 30d |
| `sensitive` | Sealed event log; KMS-encrypted column; access-audited; reads require role | 30 days |
| `secret` | Hash + metadata only; full payload never persisted | Metadata indefinite; full payload never |

Proxy reads the tag at record time and routes accordingly. Sentinel (ADR-050) provides the tag.

**PII detector**: built-in pattern set (emails, phones, credit cards, secret-shaped tokens) runs on every `normal`-tagged event. Match → fail loudly in dev (block PR), redact-and-log in prod, emit `pii.unexpected_match` event. Forces consumers to either tag correctly or expect operational pain.

## Interface (sketch)

```python
class SensitivityTier(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    SECRET = "secret"

class ReplayableLLMClient(Protocol):
    async def call(self, request: LLMRequest) -> LLMResponse: ...           # records args+response
    async def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]: ...

class ReplayableToolDispatcher(Protocol):
    async def call(self, tool_call: ToolCall) -> ToolResult: ...             # records args+result
    async def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]: ...

class ToolRegistration(BaseModel):  # extends ADR-050
    name: str
    reversibility: ToolReversibility
    sensitivity: SensitivityTier = SensitivityTier.NORMAL
    compensator: str | None = None
    impact_estimator: str | None = None
    idempotency_key: str | None = None
```

## Acceptance criteria

- [ ] Every LLM call goes through `ReplayableLLMClient`; direct `litellm.completion` invocation in engine code fails CI.
- [ ] Every tool call goes through `ReplayableToolDispatcher`; direct in-process tool invocation outside the dispatcher fails registration.
- [ ] Recorded events carry the `trace_id` and `span_id` from the active ADR-037 trace.
- [ ] `replay(trace_id)` returns events in original order.
- [ ] Tool tagged `sensitive` writes go to the sealed event store with KMS-encrypted payload column.
- [ ] Tool tagged `secret` writes hash + metadata only; full payload not persisted anywhere.
- [ ] PII detector flags untagged-`normal` events matching built-in patterns; fails dev CI; emits `pii.unexpected_match` in prod.
- [ ] Span `observability.proxy.{llm,tool}` per ADR-037.
- [ ] Hypothesis property test: for any sequence of recorded LLM + tool calls, replay yields the same logical event order.

## Open questions

1. **Sealed event store backend.** Separate Postgres schema vs same schema with KMS-encrypted column. Recommend same schema + KMS-encrypted column — minimises moving parts; access policy lives at the application layer.
2. **PII detector — built-in only or pluggable?** Recommend built-in pattern set + pluggable extension hooks (consumers register additional patterns).
3. **Replay scope.** Recorded-response replay only, or also state-replay (resume from checkpoint, used by ADR-056)? Recommend they share the event log but are distinct operations — replay re-runs orchestration; resume continues execution.
4. **Tenant-key encryption for `secret` tier.** Recommend deferred; operator-debuggability cost is high and v1 demand unclear.
5. **Recording overhead.** Every tool/LLM call writes to the event log. Recommend async/best-effort write with bounded-buffer backpressure; never block the hot path on event-log latency.

## Source references

- ADR-037 observability taxonomy.
- ADR-050 reversibility taxonomy (sensitivity field lives alongside reversibility).
- `maistro-engine:src/maistro/observability/`.
- LiteLLM and fastmcp — wrapped by the substrate proxy; not bypassed.

## Out of scope

- Deterministic re-execution (temperature-0 LLM + frozen RNG). Separate ADR if a real demand appears.
- Vendor APM choice per product (ADR-037 already covers).
- Cross-tenant replay (stronghold concern).
- Long-term archival to S3 / blob (separate ADR if needed).
