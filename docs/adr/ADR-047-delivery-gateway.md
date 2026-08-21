---
id: ADR-047
title: Outbound Delivery Gateway — Multi-channel notifier
repo: maistro-engine
kind: adr
status: Deprecated
created: 2026-05-13
substrate:
  - maistro-engine#ADR-014
  - maistro-engine#ADR-018
  - maistro-engine#ADR-046
implements: []
related:
  - maistro-engine#ADR-046
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - cross-service
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-13
  - status: Deprecated
    date: 2026-08-19
---

# ADR-047: Outbound Delivery Gateway — Multi-channel notifier

> **Convergence note (2026-08-19).** This ADR was marked `Implemented` over
> code that has no path from any process entry point, which the reachability
> sweep in
> [#360](https://github.com/Agent-StrongHold/maistro-engine/issues/360)
> surfaced and
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363)
> catalogued. It shipped and was never connected. Nothing else in the tree
> provides an outbound delivery gateway.
>
> Status moved `Implemented` → `Deprecated` rather than `Superseded`: nothing
> replaces this design, and `Superseded` requires naming a successor document.
> The code remains in the tree and in `quality/reachability-baseline.json`;
> its removal belongs to the island-elimination stage of the convergence
> effort.


## Context

Maistro has `src/maistro/api/webhooks.py` for *inbound* GitHub/CI events, but no abstraction for *outbound* messages — the agent has no substrate-blessed way to say "send this answer to the user over Telegram" or "email this report". Every product repo is on track to reinvent this.

Hermes-desktop already provides the destination list as a single first-class feature: `src/renderer/src/screens/Gateway/Gateway.tsx` exposes Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost, Email, Webhook, SMS, HomeAssistant, DingTalk, Feishu, WeCom. `Schedules.tsx` already reuses the same `DELIVER_TARGETS` list — demonstrating that schedule + delivery compose naturally. We should mirror that composition.

## Problem

No outbound channel abstraction. Product repos cannot ask the substrate to deliver an artifact and will each ship their own Slack / Telegram / email client with bespoke retry semantics.

## Solution sketch

A `Channel` protocol (mirroring `memory/protocol.py`) with one adapter per platform, registered in a `ChannelRegistry`. `TaskCreate` and `Schedule` both gain an optional `deliver: list[DeliveryTarget]` field. After a task completes, the runner enqueues `DeliveryJob` rows; a delivery worker drains them with the existing circuit-breaker / retry-with-jitter pattern from `conductor.py`. Credentials live in the existing vault — channels reference vault keys, never raw secrets.

First tranche of adapters: **Email (SMTP), Webhook (HTTPS POST), Telegram, Slack.** Everything else is a follow-up adapter PR — the protocol is the contract.

## Protocol (sketch)

```python
class DeliveryTarget(BaseModel):
    channel: Literal["email", "webhook", "telegram", "slack", ...]
    address: str                     # e.g. chat_id, email, URL
    config_ref: str | None           # vault key for per-channel creds

class DeliveryResult(BaseModel):
    target: DeliveryTarget
    status: Literal["sent", "failed", "dropped"]
    provider_message_id: str | None
    error: str | None
    attempts: int

class Channel(Protocol):
    name: str
    async def send(self, target: DeliveryTarget, payload: DeliveryPayload) -> DeliveryResult: ...
    async def health(self) -> ChannelHealth: ...
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/channels` | List registered channels + health |
| `POST` | `/v1/channels/{channel}/test` | Send synthetic payload to a target; returns `DeliveryResult` |
| `GET` | `/v1/deliveries?task_id=...` | Audit log of delivery attempts |

`TaskCreate` and `Schedule.task_template` gain `deliver: list[DeliveryTarget]`.

## Acceptance criteria

- [ ] A task created with `deliver=[{channel: "webhook", address: "https://..."}]` produces one `DeliveryJob`, one POST, and one `DeliveryResult{status: "sent"}` row.
- [ ] Channel adapter failures retry with the existing jitter schedule; after circuit-breaker open, `DeliveryResult.status = "dropped"` and `delivery.dropped_total{channel}` increments.
- [ ] Email + Webhook + Telegram + Slack adapters ship in this ADR's PR; further adapters are separate PRs against the same protocol.
- [ ] Credentials never appear in `DeliveryJob` rows, logs, or traces — only `config_ref` vault keys.
- [ ] OTel span `delivery.send{channel}` is a child of the originating `task.run` span.

## Open questions

1. **Idempotency.** Do we de-dup on `(task_id, target_hash)` so a task retry doesn't double-deliver? Recommend yes — store `delivery_key` unique index.
2. **Templating.** Does the substrate render payloads (Jinja over `ConductorOutput`) or accept pre-rendered strings only? Recommend pre-rendered for v1 — templating belongs in product repos.
3. **Inbound replies.** Several hermes channels (Telegram, Slack, Email) support inbound. Out of scope here — inbound stays in `webhooks.py` / a future ADR; this ADR is outbound-only.
4. **Channel discovery order.** Adapter import via entry-points (like skills) or hard-registered in `channels/registry.py`? Recommend entry-points so downstream repos can ship private adapters.

## Source references

- `hermes-desktop:src/renderer/src/screens/Gateway/Gateway.tsx` — channel matrix UX
- `hermes-desktop:src/renderer/src/screens/Schedules/Schedules.tsx` (`DELIVER_TARGETS`) — schedule×delivery composition precedent
- `maistro-engine:src/maistro/memory/protocol.py` — protocol-and-registry pattern to mirror
- `maistro-engine:src/maistro/api/webhooks.py` — inbound counterpart

## Out of scope

- Inbound message handling (separate ADR).
- Payload templating engine.
- Adapters beyond Email / Webhook / Telegram / Slack — each is a follow-up PR against this protocol.
- Rate-limit negotiation per channel (rely on circuit breaker for v1).
