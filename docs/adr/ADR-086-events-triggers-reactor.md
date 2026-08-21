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
Proactive automation — scheduled tasks (ADR-046), proactive producers — needs a dependable answer:
events must not be silently lost, handlers must not double-apply, and a process restart must not
strand in-flight work. This ADR pins those semantics.

## Decision

**Delivery is AT-LEAST-ONCE.** The event bus guarantees an event reaches its handlers at least once;
it may deliver more than once (retry, redelivery after crash). Consequently **handlers MUST be
idempotent** — and they reuse the existing **ADR-038 idempotency-key contract** rather than inventing
a new dedupe mechanism. A handler keyed by idempotency-key that has already applied an effect is a
no-op on redelivery.

**Triggers are declarative rules** of the form `(event-pattern -> recipe)`. The reactor evaluates
incoming events against the registered trigger patterns and, on a match, fires the bound recipe.
Triggers are data (a pattern and a recipe reference), not code — the reactor is the fixed engine that
evaluates them.

**Events and their processing are durable and replayable** via an **event log**. Events are appended
to the log before handling; a crash mid-handling **replays** from the log on restart rather than
dropping the event. Combined with idempotent handlers, replay is safe: a partially-applied handler
re-runs to completion without double-applying its committed effects.

This event log + trigger + reactor stack is the **substrate for proactive automation**: scheduled
tasks (ADR-046) and proactive producers are expressed as triggers firing recipes, so they inherit
at-least-once delivery, idempotency, and crash-replay for free.

## Acceptance criteria

- [ ] The event bus delivers each event to its handlers at least once; redelivery is possible and
      expected.
- [ ] Handlers are idempotent and key their dedupe on the ADR-038 idempotency-key contract; a
      redelivered event produces no duplicate committed effect (property test: deliver twice, observe
      one effect).
- [ ] A trigger is a declarative `(event-pattern -> recipe)` rule; the reactor fires the bound recipe
      on a pattern match.
- [ ] Events are appended to a durable event log before handling; a crash mid-handling replays from
      the log on restart rather than dropping the event.
- [ ] Scheduled tasks (ADR-046) and proactive producers are expressed as triggers and inherit the
      delivery / idempotency / replay guarantees.

## Consequences

- ADR-037 gains explicit delivery semantics; "the bus delivers events" now has a contract.
- The at-least-once + idempotent + replay combination makes proactive automation crash-safe by
  construction rather than by per-handler care.
- Triggers being data (not code) means new proactive behavior is authored as rules, not deployed as
  handler code — the reactor stays fixed.

## Out of scope

- The on-disk format and retention policy of the event log.
- The pattern language for triggers (a follow-up SPEC).
- Exactly-once / transactional delivery — explicitly not provided; idempotency is the contract.
