---
id: ADR-082
title: "Alerting, SLO, and Trace Context Propagation"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-037
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#ADR-047
  - maistro-engine#ADR-055
  - maistro-engine#ADR-058
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Observability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-082: Alerting, SLO, and Trace Context Propagation

**Status:** Proposed
**Date:** 2026-05-30
**Substrate:** ADR-037 (telemetry/event backend), ADR-038 (reliability taxonomy + error budgets).

---

## Context

The engine emits ADR-037 telemetry and tracks ADR-038 error budgets, but nothing turns those signals
into operator notifications, and nothing guarantees a trace can be followed end-to-end. Two concrete
gaps:

1. **Alerting has no home.** There is no documented path from "an error budget is burning" or
   "something failed" to "an operator is told." Worse, ad-hoc code tends to hardcode a channel
   (someone assumes Telegram, someone else assumes Slack), which makes the alert path
   deployment-specific and untestable.
2. **Traces break across hops.** A request fans out across A2A delegations and parallel waves, but
   correlation context is dropped or partially carried, so a trace cannot be reassembled. And there
   is no agreed trace backend, so deployments without a vendor backend lose traces entirely.

This ADR specifies both, reusing existing substrate rather than inventing new delivery or storage.

## Decision

Two parts.

### (A) Alerting + SLO

- **Alerts are events.** An operational alert is an ADR-037 **event** routed through the **existing
  ADR-047 multi-channel delivery gateway**. No new delivery mechanism — alerting is a producer for
  the gateway already in place.
- **Severity tiers.** Each alert carries a severity tier, and the gateway routes by tier (e.g.
  info/warning/critical map to different channels/escalation per operator config).
- **SLO-burn alerts come from error budgets.** SLO alerts are driven by the **ADR-038 error
  budgets** — when burn rate crosses a threshold, an alert event is raised. The budget is the source
  of truth for "are we out of SLO," not a hand-written rule.
- **Channels are configurable / pluggable.** This ADR **does not hardcode any channel.** It does not
  assume Telegram, Slack, email, or anything else. The **gateway + severity mechanism is the
  contract**; the **channel list is operator configuration**. A deployment with zero channels
  configured still raises the events correctly (they go nowhere, by config).

```text
ADR-038 error budget ─┐
ADR-037 failure event ─┼─→ alert event (severity tier) ─→ ADR-047 gateway ─→ [operator-configured channels]
                       ┘                                                       (Telegram? Slack? email? — config, not code)
```

### (B) Trace context propagation

- **Propagate the maximal correlation context across every hop** — A2A delegation and parallel waves
  included. Carry **every id that can be passed**, not just a trace id:

  ```text
  trace · session · conversation · agent · dag · user · creator · initiator · owner
  ```

  Any hop that has an id MUST forward it; a hop that lacks one MUST NOT strip the ones it does have.
- **Pluggable trace backend with graceful degradation.** Store traces in **Arize Phoenix OR
  Langfuse** (the ADR-037 backend choice), and **fall back to a SQL DB** when neither is configured.
  This is the same "works with anything, degrade gracefully" pattern already used for embeddings:
  prefer the rich backend, but never lose the trace because a vendor backend is absent.

```text
trace backend:  Phoenix ─or─ Langfuse  (ADR-037 choice)
                   └── fallback ──→ SQL DB   (always available)
```

## Acceptance criteria

- [ ] An operational alert is emitted as an ADR-037 event and delivered via the ADR-047 gateway —
      no separate delivery path.
- [ ] Every alert carries a severity tier and the gateway routes by tier.
- [ ] An SLO-burn alert is triggered from the ADR-038 error budget crossing a threshold, not from a
      hardcoded rule.
- [ ] No channel is hardcoded; the channel list is operator config, and the system runs (raising
      events) with zero channels configured.
- [ ] Correlation context carries trace, session, conversation, agent, dag, user, creator, initiator,
      and owner ids across A2A delegation and parallel waves.
- [ ] A hop forwards every id it received; it never strips an id it cannot enrich.
- [ ] Traces are stored in Phoenix or Langfuse when configured (ADR-037), and fall back to a SQL DB
      when neither is available — no configuration loses traces.
- [ ] A trace spanning an A2A delegation and a parallel wave can be reassembled from the stored
      context.

## Consequences

- ADR-038 error budgets and ADR-037 events become actionable: budget burn and failures reach an
  operator without new infrastructure.
- Channel-agnostic alerting means the same build runs in any deployment; the channel choice is a
  config diff, not a code change, and the path is testable against the gateway alone.
- Maximal-context propagation makes fan-out traces reconstructable, at the cost of threading more ids
  through every hop boundary.
- The SQL fallback guarantees observability on deployments with no vendor trace backend, mirroring the
  embeddings degrade-gracefully pattern operators already understand.

## Out of scope

- Specific burn-rate thresholds and severity-to-channel mappings (operator configuration / follow-up
  SPEC).
- The concrete channel adapters behind the ADR-047 gateway (each is its own integration).
- The trace storage schema and retention policy for the SQL fallback.
- Dashboard/visualization of traces and SLOs — consumes this, specified elsewhere.
