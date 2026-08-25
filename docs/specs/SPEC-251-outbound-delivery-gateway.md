---
id: SPEC-251
title: "Outbound delivery gateway — Channel protocol, registry, idempotent dispatch (ADR-047)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-014
  - maistro-engine#ADR-018
implements:
  - maistro-engine#ADR-047
related:
  - maistro-engine#ADR-046
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - cross-service
tests:
  - packages/maistro-core/tests/delivery/test_dispatch.py
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-251: Outbound delivery gateway — Channel protocol, registry, idempotent dispatch

> **Convergence note (2026-08-19).** This spec is marked `Implemented` over
> code with no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). It
> tracks ADR-047, now `Deprecated`.
>
> The status is left unchanged because the spec lifecycle has no way to
> express this. From `Implemented` a spec may only become `Superseded`, which
> requires a `superseded-by`, and no successor document exists. There is no
> `Deprecated` state for specs as there is for ADRs. Correcting this needs
> either the successor spec or a lifecycle change, so the note carries the
> truth in the meantime.


## Context

ADR-047 asks for a substrate-blessed way for an agent to deliver an artifact over an outbound
channel (Telegram, Slack, email, webhook, ...) with retry/circuit-breaking and no credentials
ever appearing in job rows or logs. Nothing implementing this exists — `maistro/agents/delivery/`
referenced in CLAUDE.md is empty, and there is no `Channel` protocol or registry. This SPEC
scopes the load-bearing core ADR-047 needs before any real network adapter can be written: the
`Channel` protocol, `DeliveryTarget`/`DeliveryResult`/`DeliveryPayload` types, a `ChannelRegistry`,
and `dispatch()` — the retry/circuit-breaker/idempotency orchestration that wraps any channel
implementation, reusing `maistro.resilience.backoff` and `maistro.agents.circuit_breaker`
rather than reinventing retry semantics.

## Goals

- Add `maistro/delivery/types.py`: `DeliveryTarget` (`channel`, `address`, `config_ref:
  str | None`), `DeliveryPayload` (`text: str`, `metadata: dict[str, str]`), `DeliveryResult`
  (`target`, `status: Literal["sent", "failed", "dropped"]`, `provider_message_id: str | None`,
  `error: str | None`, `attempts: int`).
- Add `maistro/delivery/protocols.py`: `Channel` Protocol — `name: str`,
  `async def send(self, target: DeliveryTarget, payload: DeliveryPayload) -> DeliveryResult`,
  `async def health(self) -> ChannelHealth`.
- Add `maistro/delivery/registry.py`: `ChannelRegistry` — `register(channel: Channel)`,
  `get(name: str) -> Channel`, `list_channels() -> list[str]`; raises `KeyError` on unknown
  channel name (no silent fallback — ADR-047 wants explicit channel discovery).
- Add `maistro/delivery/dispatch.py`: `async def dispatch(registry, target, payload, *,
  breaker: CircuitBreaker | None = None, max_attempts: int = 3, seen_keys: set[str] | None =
  None) -> DeliveryResult`:
  - Idempotency: computes `delivery_key = f"{task_id}:{target.channel}:{target.address}"`
    (caller-supplied `task_id` via `DeliveryPayload.metadata["task_id"]`, empty string if
    absent); if `delivery_key in seen_keys`, returns immediately with `status="dropped"`,
    `attempts=0`, without calling the channel — no double-delivery on retry.
  - If the breaker is open (`breaker.allow_request() is False`), returns
    `status="dropped"` without calling the channel.
  - Otherwise calls `channel.send()`, retrying on exception up to `max_attempts` with
    `maistro.resilience.backoff.jittered_backoff` between attempts; each failure calls
    `breaker.record_failure()`if a breaker is supplied; success calls `breaker.record_success()`.
  - After all attempts exhausted, returns `status="failed"` with the last error message.
- Credentials never appear in any type above — only `config_ref` (a vault key string); this
  SPEC's types make it structurally impossible to carry a raw secret (no such field exists).

## Non-goals

- Real channel adapters (SMTP, Telegram, Slack, generic Webhook) — each is a follow-up PR
  against the `Channel` protocol, per ADR-047's own phasing. This SPEC validates the protocol
  with an in-memory fake channel only.
- The `/v1/channels`, `/v1/channels/{channel}/test`, `/v1/deliveries` HTTP routes — follow-up
  once a maistro-server route exists to host the registry.
- `TaskCreate`/`Schedule.deliver` field wiring — follow-up once the route/task-runner
  integration point is chosen.
- Persistent `DeliveryJob` storage / audit log — `seen_keys` here is an in-memory set the
  caller owns; a durable idempotency store is follow-up infra.
- OTel `delivery.send{channel}` span — added at the route/runner boundary, not here.
- Entry-point-based adapter discovery — `ChannelRegistry.register()` is explicit for now;
  entry-points are a follow-up once more than the in-tree fake channel exists.

## Decision

```python
# maistro/delivery/types.py
@dataclass(frozen=True)
class DeliveryTarget:
    channel: str
    address: str
    config_ref: str | None = None

@dataclass(frozen=True)
class DeliveryPayload:
    text: str
    metadata: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class DeliveryResult:
    target: DeliveryTarget
    status: Literal["sent", "failed", "dropped"]
    provider_message_id: str | None
    error: str | None
    attempts: int

# maistro/delivery/protocols.py
@dataclass(frozen=True)
class ChannelHealth:
    healthy: bool
    detail: str = ""

class Channel(Protocol):
    name: str
    async def send(self, target: DeliveryTarget, payload: DeliveryPayload) -> DeliveryResult: ...
    async def health(self) -> ChannelHealth: ...

# maistro/delivery/registry.py
class ChannelRegistry:
    def register(self, channel: Channel) -> None: ...
    def get(self, name: str) -> Channel: ...
    def list_channels(self) -> list[str]: ...

# maistro/delivery/dispatch.py
async def dispatch(
    registry: ChannelRegistry,
    target: DeliveryTarget,
    payload: DeliveryPayload,
    *,
    breaker: CircuitBreaker | None = None,
    max_attempts: int = 3,
    seen_keys: set[str] | None = None,
) -> DeliveryResult: ...
```

## Acceptance criteria

- [x] `dispatch()` against a fake channel that always succeeds returns
      `DeliveryResult(status="sent", attempts=1)`.
- [x] `dispatch()` against a fake channel that fails `N` times then succeeds returns
      `status="sent"`, `attempts=N+1`, with `N` jittered-backoff sleeps in between (mocked sleep
      asserted to have been called `N` times).
- [x] `dispatch()` against a fake channel that always fails, with `max_attempts=3`, returns
      `status="failed"`, `attempts=3`, `error` non-empty.
- [x] A second `dispatch()` call with the same `(task_id, channel, address)` key already in
      `seen_keys` returns `status="dropped"`, `attempts=0`, without invoking `channel.send()`.
- [x] An open `CircuitBreaker` causes `dispatch()` to return `status="dropped"` without calling
      `channel.send()`.
- [x] `ChannelRegistry.get()` on an unregistered channel name raises `KeyError`.
- [x] No `DeliveryTarget`/`DeliveryPayload`/`DeliveryResult` field can hold a raw secret —
      structural review, not a runtime check (covered by the type definitions themselves having
      no such field; asserted via `dataclasses.fields()` name check in the test as a regression
      guard).

## Testing

- `packages/maistro-core/tests/delivery/test_dispatch.py` (new) — `dispatch()` retry/backoff/
  circuit-breaker/idempotency behavior against an in-memory fake `Channel`, plus the
  registry's unknown-channel `KeyError` and the no-secret-field regression guard.

## Open questions

- Whether `seen_keys` should become a `Protocol` (pluggable durable store) once a real task
  runner needs persistence across process restarts — deferred; an in-memory `set` is sufficient
  for this SPEC's scope and the caller can swap it later without changing `dispatch()`'s shape
  (any `MutableSet`-like object satisfies `in`/`.add()`).

## References

- `packages/maistro-core/src/maistro/resilience/backoff.py`
- `packages/maistro-core/src/maistro/agents/circuit_breaker.py`
- [ADR-047: Outbound Delivery Gateway](../adr/ADR-047-delivery-gateway.md)
