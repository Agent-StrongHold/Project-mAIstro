---
id: SPEC-081226-7248
title: Event and Checkpoint Model
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-12
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
  - status: AC Defined
    date: 2026-08-12
substrate:
  - maistro-engine#ADR-081226-7248
implements: [maistro-engine#ADR-081226-7248, maistro-engine#ADR-083026-6e2a]
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
ac-modules:
  AC-1: maistro.events.durable_log
  AC-2: maistro.events.durable_log
  AC-3: maistro.events.outbox
  AC-4: maistro.events.invocations
  AC-5: maistro.events.envelope
  AC-6: maistro.graph.durable_runs.execution_store
  AC-7: maistro.graph.durable_runs.execution_store
  AC-8: maistro.graph.durable_runs.executor
  AC-9: maistro.graph.durable_runs.executor
  AC-10: maistro.events.durable_log
  AC-11: maistro.events.envelope
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-7248: Event and Checkpoint Model

- **Status:** Active
- **Date:** 2026-08-12
- **ADR:** `ADR-081226-7248`

## Event requirements

1. Canonical Event MUST contain `event_id`, `sequence`, `timestamp`, `workspace_id`, `type`, `payload` and actor/provenance; execution/session correlation IDs are included when applicable.
2. `event_id` MUST be unique and suitable for idempotent consumer processing.
3. `sequence` MUST be monotonic within the Workspace durable event stream and assigned by one canonical sequencing authority.
4. Canonical lifecycle events MUST be durably recoverable; an in-memory bus alone is insufficient.
5. Run/NodeRun/Attempt/Invocation transitions MUST emit correlated events after/with durable state commitment using transaction/outbox/reconciliation semantics.
6. A reconnecting UI/consumer MUST be able to resume from a known sequence/event position.
7. Domain payloads MAY vary but envelope correlation MUST remain stable.
8. Existing GraphEvent/StageEvent/package events MAY be projections during migration but MUST preserve canonical IDs on migrated paths.
9. Logs/traces/metrics MUST reference canonical correlation IDs but need not be duplicated as durable Events unless they represent product/domain facts.
10. Consumers MUST tolerate unknown event types/payload versions according to compatibility policy rather than corrupt ordering.

## Checkpoint requirements

1. Checkpoint MUST be immutable after creation.
2. Checkpoint MUST resolve Workspace and Run ownership and SHOULD identify NodeRun/Attempt where applicable.
3. Checkpoint MUST record state/schema compatibility metadata sufficient to reject unsafe resume.
4. Resume MUST create a new Attempt referencing `resume_checkpoint_id` while preserving non-terminal Run/NodeRun identity.
5. Durable graph checkpoint MUST be able to include/reference GraphExecutionState and graph snapshot identity.
6. Recovery MUST detect stale `running` state with no valid active Attempt.
7. Recovery MUST enforce crash-loop/retry policy before creating a replacement Attempt.
8. Checkpoint creation MUST emit a correlated canonical Event.
9. Large state MAY be stored as Artifact/storage locator; the Checkpoint record retains hash/version/provenance.

## Acceptance Criteria

```gherkin
Feature: Event and Checkpoint model

  @AC-1
  Scenario: Concurrent producers share one deterministic sequence
    Given two producers emitting into one Workspace stream
    When both emit concurrently
    Then the event store assigns a deterministic monotonic ordering

  @AC-2
  Scenario: A reconnecting client replays from a sequence
    Given a client that disconnects after a known sequence number
    When it reconnects and supplies that sequence
    Then it receives the events it missed
    And no durable history is lost

  @AC-3
  Scenario: A committed transition always gets its event
    Given a Run transition committed to state
    When the process crashes before fanout
    Then reconciliation produces the corresponding durable canonical event

  @AC-4
  Scenario: Duplicate delivery does not duplicate effects
    Given an idempotent consumer keyed by event_id
    When the same event is delivered twice
    Then its effect occurs once

  @AC-5
  Scenario: Adapted package events keep canonical correlation
    Given a Builders StageEvent or GraphEvent
    When it passes through its adapter
    Then it carries canonical workspace_id, run_id and node_run_id

  @AC-6
  Scenario: A waiting NodeRun releases its worker and resumes
    Given a NodeRun that must wait
    When it creates a Checkpoint
    Then the worker is released
    And after restart it resumes through a new Attempt referencing that Checkpoint

  @AC-7
  Scenario: Incompatible checkpoint metadata refuses resume
    Given a Checkpoint whose compatibility metadata is invalid
    When resume is attempted
    Then it is rejected

  @AC-8
  Scenario: Stale running state is reconciled, not displayed forever
    Given a NodeRun marked running whose worker is dead or missing
    When reconciliation runs
    Then the state is detected and reconciled rather than left active indefinitely

  @AC-9
  Scenario: Crash-loop policy bounds automatic recovery
    Given a NodeRun that fails immediately on every recovery Attempt
    When recovery repeats
    Then policy stops it rather than retrying without limit

  @AC-10
  Scenario: Chronology reconstructs from canonical events
    Given canonical events for a Run
    When UI history and audit query them
    Then both reconstruct the same Run chronology

  @AC-11
  Scenario: Telemetry joins to events by correlation id
    Given metrics and traces for an Invocation
    When they are joined to its canonical Event and Run
    Then correlation IDs suffice
    And the telemetry need not be carried in Event payloads

  @AC-12
  Scenario: A second canonical sequence is a violation
    Given the architecture fitness checks
    When a migrated publisher invents a second canonical sequence for one Workspace stream
    Then the checks reject it
```

## Non-goals

This SPEC does not require event sourcing as the sole state persistence model, force every telemetry record into the event log, or prescribe one message broker.
