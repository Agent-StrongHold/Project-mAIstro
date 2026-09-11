---
id: ADR-086
title: "Events, Triggers, and the Reactor"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-037
implements: []
related:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-046
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-086: Events, Triggers, and the Reactor

**Status:** Proposed
**Date:** 2026-05-30
**Specifies the delivery semantics** of the ADR-037 event bus and the trigger/reactor layer that
turns events into action — the substrate every proactive behavior in the engine stands on.

---

## Context

ADR-037 names the event bus and the `policy.decision` / `security.violation` events, but does not say
how events are delivered, what happens on a crash mid-handling, or how an event causes work to run.
Proactive automation — scheduled tasks (ADR-046), proactive producers — needs a dependable
answer: events must not be silently lost, and a process restart must not strand in-flight work. A
local dispatch record cannot make an arbitrary remote commit exactly-once, so this ADR also states
where idempotency must be proven.

## Decision

**Delivery is AT-LEAST-ONCE.** The event bus guarantees an event reaches its handlers at least once;
it may deliver more than once (retry, redelivery after crash). The `(trigger_id, event_id)`
Invocation row deduplicates MAIstro dispatch only; it does not deduplicate a remote commit.
Therefore an effectful handler is eligible for automatic replay only when it consumes the stable
ADR-038 idempotency key and stores that key at its own effect commit boundary. A handler that cannot
prove this is `UNSAFE` for automatic replay and must be held for reconciliation or moved to the
canonical governed Capability/Provider/Binding/Invocation seam (#55).

**Triggers are declarative rules** of the form `(event-pattern -> recipe)`. The reactor evaluates
incoming events against the registered trigger patterns and, on a match, fires the bound recipe.
Triggers are data (a pattern and a recipe reference), not code — the reactor is the fixed engine that
evaluates them.

**Events and their processing are durable and replayable** via an **event log**. Events are appended
to the log before handling; a crash mid-handling **replays** from the log on restart rather than
dropping the event. For an opted-in idempotent handler, the HTTP delivery repeats the same stable
key, so a partially-applied handler can re-run without double-applying its committed effect. A
response loss or timeout remains an ambiguous remote outcome; HTTP 2xx and the local SUCCESS write
are not one transaction.

This event log + trigger + reactor stack is the **substrate for proactive automation**: scheduled
tasks (ADR-046) and proactive producers are expressed as triggers firing recipes, so they inherit
at-least-once delivery and crash-replay. Effect safety still depends on each trigger's declared
handler-owned idempotency contract.

## Acceptance criteria

- [ ] The event bus delivers each event to its handlers at least once; redelivery is possible and
      expected.
- [ ] Opted-in handlers consume and durably deduplicate the stable ADR-038 idempotency key;
      unsafe handlers are not automatically replayed (property test: deliver twice, observe one
      effect for the opted-in handler).
- [ ] A trigger is a declarative `(event-pattern -> recipe)` rule; the reactor fires the bound recipe
      on a pattern match.
- [ ] Events are appended to a durable event log before handling; a crash mid-handling replays from
      the log on restart rather than dropping the event.
- [ ] Scheduled tasks (ADR-046) and proactive producers are expressed as triggers and inherit
      at-least-once delivery; effect idempotency/replay safety is conditional on the handler
      contract.

## Consequences

- ADR-037 gains explicit delivery semantics; "the bus delivers events" now has a contract.
- The at-least-once + handler-owned idempotency-key + replay combination makes opted-in proactive
  automation safe across post-effect crashes; the local Invocation row alone makes no such claim.
- Triggers being data (not code) means new proactive behavior is authored as rules, not deployed as
  handler code — the reactor stays fixed.

## Out of scope

- The on-disk format and retention policy of the event log.
- The pattern language for triggers (a follow-up SPEC).
- Exactly-once / transactional delivery — explicitly not provided; handler-owned idempotency is
  the supported contract, and the local Invocation row is not an external-effect authority.
