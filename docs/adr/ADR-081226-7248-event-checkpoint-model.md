---
id: ADR-081226-7248
title: Event and Checkpoint Model
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
substrate: []
implements: []
related:
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081226-69ee
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-core/src/maistro/events
  - packages/maistro-core/src/maistro/graph/durable_runs
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-081226-7248: Event and Checkpoint Model

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** MAIstro maintainers
- **Technical Area:** Events, durable history, checkpoints, recovery

## Context

MAIstro has GraphEvent, Builders StageEvent, event-bus events, collaboration streams, runtime callbacks, audit records and package-specific progress messages. Checkpoint/recovery state is also split between task recovery and durable graphs. The product needs one durable event envelope and one checkpoint concept that can support live UI, audit, observability correlation, recovery, notifications and memory extraction.

## Decision

### Canonical Event envelope

Product/domain execution events use one envelope:

```text
Event
├── event_id
├── sequence
├── timestamp
├── workspace_id
├── run_id?
├── node_run_id?
├── attempt_id?
├── invocation_id?
├── session_id?
├── type
├── payload
└── actor/provenance
```

Domain-specific payload schemas remain domain-specific. The envelope and correlation semantics are canonical.

### Sequencing

`sequence` is assigned by the canonical durable event store and is monotonic within a Workspace event stream. It need not be gap-free. System/global events outside a Workspace require an explicit non-Workspace stream scope.

Subsystems MUST NOT establish competing sequence authorities for the same canonical stream. Package-local sequence fields may remain as payload metadata when the domain truly needs them.

### Durable append before fanout

Canonical events are durable facts. Live buses/SSE/WebSocket/callbacks are delivery mechanisms over the durable envelope, not the sole source of history.

Where state transition and event persistence cannot be one transaction, use an outbox/reconciliation strategy so a committed Run transition cannot permanently lack its corresponding event and an event cannot claim a state transition that never committed.

### Event scope

Not every log line or metric is a canonical Event. Canonical Events represent product/domain facts worth durable correlation/replay. Logs, traces and metrics reference the same IDs but may remain in observability systems.

### Event types

Event types SHOULD be stable namespaced identifiers such as `run.started`, `node_run.waiting`, `attempt.cancelled`, `invocation.completed`, `checkpoint.created` and package-domain equivalents. Payload schema evolution MUST be version-aware where consumers require it.

### Existing event models become projections/adapters

GraphEvent, Builders StageEvent, collaboration events and package-specific streams may remain temporary projections, but migrated paths must carry canonical IDs and derive ordering from the canonical event record where applicable.

### Canonical Checkpoint

A Checkpoint is an immutable persisted resumability fact, not a second Run lifecycle.

A Checkpoint records at least:

- `checkpoint_id`
- `workspace_id`
- `run_id`
- optional `node_run_id` / `attempt_id`
- created time/reason
- state/schema version
- resumable state locator/payload/hash
- executable/version compatibility metadata
- provenance

Graph-specific state may be checkpointed as GraphExecutionState. NodeType-specific resumable state may be referenced as domain checkpoint data/artifacts.

### Resume uses a new Attempt

Resuming from a Checkpoint preserves Run/NodeRun logical identity and creates a new Attempt referencing the checkpoint source.

### Recovery

Recovery examines Run/NodeRun/Attempt/Checkpoint state and event history. It performs stale-active detection, compatibility validation, crash-loop policy and explicit new-Attempt creation. It does not create a competing recovery task lifecycle.

## Consequences

- UI and post-run inspection can use the same durable history.
- Audit/security decisions correlate directly to execution.
- Event delivery can reconnect/replay after disconnect.
- Task and durable graph recovery can converge on the same checkpoint concept.
- Existing package buses require adapters during migration.

## Compliance

A path complies when durable product events use the canonical envelope/Workspace sequence, live delivery is recoverable from durable history, checkpoints are immutable resumability facts, and resume/recovery preserves logical Run/NodeRun identity while creating a new Attempt.

## References

- `ADR-081226-a66b`
- `ADR-081226-69ee`
- `docs/analysis/ARCHITECTURE-CONVERGENCE-MATRIX.md`
