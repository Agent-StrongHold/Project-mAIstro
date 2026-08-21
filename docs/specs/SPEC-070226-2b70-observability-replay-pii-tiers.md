---
id: SPEC-070226-2b70
title: "Observability extensions: replayable LLM/tool proxies and PII sensitivity-tier routing"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-07-02
substrate:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-050
  - maistro-engine#ADR-055
  - maistro-engine#SPEC-228
implements:
  - maistro-engine#ADR-055
related:
  - maistro-engine#ADR-053
  - maistro-engine#ADR-056
  - maistro-engine#SPEC-223
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/observability/test_tiers.py
  - packages/maistro-core/tests/observability/test_replay.py
  - packages/maistro-core/tests/observability/test_proxy.py
ac-modules:
  AC-1: maistro.observability.proxy
  AC-2: maistro.observability.replay
  AC-3: maistro.observability.proxy
  AC-4: maistro.observability.replay
  AC-5: maistro.observability.replay
  AC-6: maistro.observability.replay
  AC-7: maistro.observability.tiers
  AC-9: maistro.observability.proxy
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-2b70: Observability extensions — replayable proxies and PII sensitivity tiers

## Context

ADR-055 extends ADR-037 with two capabilities: (1) recorded-response replay — substrate-owned
proxies record every LLM call and tool call so orchestration code can be deterministically
re-executed against recorded responses; and (2) PII sensitivity tiers — `normal`/`sensitive`/
`secret` tags that route event payloads to different storage/retention regimes.

This SPEC realizes both, and resolves ADR-055's five open questions with concrete choices
(recorded there as recommendations; locked in here).

## Goals

- `ReplayableLLMClient` and `ReplayableToolDispatcher` proxies that record args + responses into
  the ADR-037 event log, carrying the active trace/span ids.
- `replay(trace_id)` re-runs orchestration against recorded responses without re-invoking LLMs
  or tools.
- `SensitivityTier` tag on tool registrations (extends ADR-050 `ToolRegistration`) and recipe-level
  prompt/response tagging (ADR-053 overlay-mergeable, `merge: replace`).
- Tier routing: `normal` → standard event log; `sensitive` → KMS-encrypted payload column with
  access audit; `secret` → hash + metadata only, payload never persisted.
- Built-in PII detector on `normal`-tagged events (reuses SPEC-223's pattern catalogue): fail
  loudly in dev, redact-and-log + `pii.unexpected_match` event in prod.
- Registration-time enforcement: an agent whose tools/LLM client bypass the proxies fails to
  register; CI grep forbids direct `litellm.completion` in engine code.

## Non-goals

- Prompt/model-bug replay (temperature-0 + frozen RNG deterministic re-execution) — ADR-055
  explicitly bounds replay to orchestration debugging.
- Tenant-key encryption for the `secret` tier (ADR-055 OQ4 — deferred, per its own recommendation).
- External streaming of recorded events (Kafka etc.).

## Decision

### Decisions on ADR-055's open questions

1. **Sealed store backend**: same Postgres schema, KMS-encrypted `payload_encrypted` column,
   application-layer access policy (per ADR-055's recommendation).
2. **PII detector**: built-in pattern set from SPEC-223's catalogue + a `register_pattern()`
   extension hook.
3. **Replay scope**: recorded-response replay only; shares the event log with ADR-056 resume but
   is a distinct operation (`replay` re-runs orchestration; `resume` continues execution).
4. **Tenant-key encryption**: deferred.
5. **Recording overhead**: async best-effort writer with a bounded buffer (default 10k events);
   on buffer overflow, drop `normal`-tier records with a `observability.record_dropped` counter —
   never block the hot path. `sensitive`/`secret` records are never dropped silently (blocking
   write with 100ms budget, then error).

### Proxy interfaces

```python
class SensitivityTier(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    SECRET = "secret"

@dataclass(frozen=True)
class ReplayEvent:
    trace_id: str
    span_id: str
    seq: int                       # monotonic per trace — replay ordering key
    kind: Literal["llm", "tool"]
    request_hash: str              # sha256 of canonicalised args
    payload: dict | None           # None for secret tier
    tier: SensitivityTier

class ReplayableLLMClient(Protocol):
    async def call(self, request: LLMRequest) -> LLMResponse: ...
    async def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]: ...

class ReplayableToolDispatcher(Protocol):
    async def call(self, tool_call: ToolCall) -> ToolResult: ...
    async def replay(self, trace_id: str) -> AsyncIterator[ReplayEvent]: ...
```

Replay mode: proxies are constructed for a `replay_source=trace_id`
(`create_replay_proxies(store, replay_source)` builds an LLM + tool proxy pair sharing one
`ReplaySession` cursor); the proxies then serve recorded responses matched by
`(seq, request_hash)` and never touch the inner client. A request whose hash does not match the
recorded one at that position raises `ReplayDivergenceError` (the orchestration bug you were
looking for, surfaced as the diff between recorded and attempted request).

### Tier routing and storage

Storage is realised as a `RecordStore` protocol (`maistro.observability.replay`), not a fixed
SQL schema: `InMemoryRecordStore` is the reference implementation, and a Postgres store (the
originally sketched `tier`/`payload_encrypted`/`payload_hash` columns + `sealed_access_audit`
table) plugs in behind the same protocol. KMS is likewise realised as injected
`encryptor`/`decryptor` callables (`bytes -> bytes`) so products wire a real KMS envelope
without a hard dependency in core.

- `normal`: full payload stored as-is (ADR-037 retention).
- `sensitive`: payload encrypted via the injected encryptor; readable only through
  `RecordStore.read_sensitive_payload(trace_id, seq, accessor, reason)`, which writes an
  `AccessAuditRecord` per read. (Scope enforcement and the 30-day retention job live with the
  Postgres store implementation.)
- `secret`: `request_hash` + metadata only; payload bytes never persisted anywhere.

### Registration-time enforcement

- `ToolRegistration` gains `sensitivity: SensitivityTier = NORMAL` (extends ADR-050 shape).
- Agent factory asserts the wired LLM client and tool dispatcher are the proxy implementations
  (`isinstance` on the protocol's registered concrete types); otherwise `AgentRegistrationError`.
- CI: `grep -rn "litellm.completion\|litellm.acompletion" packages/maistro-core/src` outside
  `observability/proxy.py` fails the lint job.

**Wiring status:** the library layer is implemented in `maistro.observability`
(`tiers.py`, `replay.py`, `proxy.py`). Container/agent-factory wiring and the CI grep rule are
follow-up work outside this change's scope (container.py deliberately untouched); today no core
code calls `litellm` directly, so the grep rule can be added to ci.yml at wiring time.

## Acceptance criteria

```gherkin
Feature: Replayable LLM/tool proxies and PII sensitivity-tier routing

  @AC-1
  Scenario: Recorded calls carry trace context and one shared sequence
    Given an LLM proxy and a tool proxy sharing a trace
    When calls are made alternately through both
    Then every ReplayEvent carries the active trace_id and span_id
    And the seq numbers are monotonic across both proxies, not per-proxy
    And each event's request hash is a canonical sha256 of the request

  @AC-2
  Scenario: Replay yields events in their original order
    Given a recorded trace of arbitrarily interleaved calls
    When the trace is replayed
    Then the events are yielded in original seq order

  @AC-3
  Scenario: Replay never reaches the real client
    Given a recorded trace and a real client that raises if called
    When the orchestration path is re-run in replay mode
    Then the recorded responses are served
    And the real client is never invoked

  @AC-4
  Scenario Outline: A replay that stops matching its recording raises
    Given a recorded trace
    When the replayed call <divergence>
    Then ReplayDivergenceError is raised naming the seq and both hashes

    Examples:
      | divergence                       |
      | sends a changed request          |
      | swaps the call kind              |
      | runs past the end of the trace   |

  @AC-5
  Scenario: Sensitive payloads are readable only through the audited path
    Given a call recorded at the sensitive tier
    When its payload is read through the scoped read path
    Then the payload is returned
    And an AccessAuditRecord is written for that read
    But reading a sensitive payload that does not exist raises

  @AC-6
  Scenario: Secret payloads persist as hash and metadata only
    Given a call recorded at the secret tier
    When the stored record is examined for any generated payload
    Then no payload bytes appear in any stored field
    And replaying it raises ReplayPayloadUnavailableError

  @AC-7
  Scenario Outline: PII in a normal-tier payload is caught
    Given the PII detector in <mode> mode
    When a normal-tier event containing <token> is recorded
    Then it <behaviour>

    Examples:
      | mode | token               | behaviour                                          |
      | dev  | an email address    | raises UnexpectedPIIError                          |
      | dev  | a secret-shaped key | raises UnexpectedPIIError                          |
      | prod | an email address    | redacts a copy and emits pii.unexpected_match      |

  @AC-7
  Scenario: The detector leaves the caller's object alone and skips sealed tiers
    Given the PII detector in prod mode
    When a normal-tier payload containing an email is recorded
    Then the caller's own object is not mutated
    And a sensitive-tier payload is not scanned at all, being already sealed

  @AC-8
  Scenario: Non-proxy LLM access is impossible
    Given engine code that calls litellm directly
    When CI runs
    Then the build fails
    And an agent wired with a non-proxy client fails registration

  @AC-9
  Scenario Outline: Recording never blocks the hot path
    Given a record writer whose buffer is full
    When a <tier>-tier record is submitted
    Then it <behaviour>

    Examples:
      | tier      | behaviour                                                  |
      | normal    | is dropped, incrementing observability.record_dropped      |
      | sensitive | raises rather than being silently dropped                  |
      | secret    | raises rather than being silently dropped                  |

  @AC-9
  Scenario: Submission returns without waiting for the write
    Given a record writer with a slow backing store
    When a normal-tier record is submitted
    Then submission returns without awaiting the write
    And a later flush persists the buffered events
```

> **AC-8 is deliberately unproven.** It needs container/agent-factory wiring
> plus a ci.yml grep rule — see the wiring status above. No test claims it, so
> the ladder reports it as `declared` and holds this spec's tier there.

## Testing

- Unit: tier routing per tag; hash computation stability; bounded-buffer overflow behaviour.
- Integration: record a small orchestration run (2 LLM calls, 3 tool calls), replay it, assert
  identical orchestration decisions and zero real invocations.
- Property (Hypothesis, per ADR-055): for any sequence of recorded LLM + tool calls, replay yields
  the same logical event order; for any payload, secret tier persists no payload bytes.
- Reuses SPEC-223 redaction fixtures for the PII detector patterns.

## Open questions

- Whether replay should be exposed as a CLI (`maistro replay <trace_id>`) in this phase or only as
  a library API (leaning: library first, CLI follow-up).

## References

- [ADR-055: Observability extensions](../adr/ADR-055-observability-replay-and-pii-tiers.md)
- [ADR-037: Observability](../adr/ADR-037-observability-taxonomy.md)
- [SPEC-223: Secret redaction](SPEC-223-secret-redaction.md)
- [SPEC-228: Observability baseline gaps](SPEC-228-observability-baseline-gaps.md)
