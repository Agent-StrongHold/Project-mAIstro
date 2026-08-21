---
id: SPEC-081226-a66b
title: Run, NodeRun and Attempt Lifecycle
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
  - maistro-engine#ADR-081226-a66b
implements:
  - maistro-engine#ADR-081226-a66b
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-69ee
  - maistro-engine#ADR-081426-1f7c
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-core/src/maistro/runs
  - packages/maistro-core/src/maistro/runtime
ac-modules:
  AC-1: maistro.runs.model
  AC-2: maistro.runs.model
  AC-3: maistro.runs.model
  AC-4: maistro.runs.model
  AC-5: maistro.graph.durable_runs.attempt_executor
  AC-6: maistro.graph.durable_runs.attempt_executor
  AC-7: maistro.graph.durable_runs.attempt_executor
  AC-8: maistro.graph.durable_runs.attempt_executor
  AC-9: maistro.graph.durable_runs.executor
  AC-10: maistro.runs.model
  AC-11: maistro.runs.model
  AC-12: maistro.runs.model
  AC-13: maistro.runs.service
  AC-14: maistro.runs.service
  AC-15: maistro.graph.durable_runs.executor
  AC-16: maistro.runs.model
  AC-17: maistro.runs.service
  AC-18: maistro.runs.service
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-a66b: Run, NodeRun and Attempt Lifecycle

- **Status:** Active
- **Date:** 2026-08-14 revision
- **ADR:** `ADR-081226-a66b`

## Required model

```text
Run(workspace_id, project_id)
└── NodeRun[]
    └── Attempt[]
        └── ExecutionRuntime(execution_id = attempt_id)
```

### Required Run fields

At minimum:

```text
run_id
workspace_id
project_id
status
created_at
updated_at
parent_run_id?
parent_node_run_id?
executable_snapshot/reference
provenance
result/error?
```

### Required NodeRun fields

At minimum:

```text
node_run_id
run_id
node_id/snapshot identity
status
ordinal
created_at
updated_at
result/error?
```

### Required Attempt fields

At minimum:

```text
attempt_id
node_run_id
ordinal
status/outcome
runtime/executor identity
created_at
started_at?
finished_at?
deadline?
resume_checkpoint_id?
result/error?
runtime metrics?
```

## Requirements

### R1. Canonical Run states

Run status MUST be one of `created`, `queued`, `running`, `waiting`, `paused`, `completed`, `failed`, `cancelled`, `timed_out`.

### R2. Scope identity

Run creation MUST copy `workspace_id` and `project_id` from the captured Graph snapshot. Both remain immutable scope identity for that Run. A Run and its Graph snapshot MUST agree on both values.

### R3. Transition validation

Canonical services MUST reject illegal transitions. Terminal Run states MUST NOT transition back to non-terminal states.

### R4. Retry identity

Retrying a NodeRun MUST create a new Attempt while preserving `run_id` and `node_run_id`.

### R5. Resume identity

Resuming a paused/waiting NodeRun from a Checkpoint MUST create a new Attempt under the same NodeRun unless the NodeRun already reached a terminal logical state.

### R6. Physical exclusivity

A NodeRun MUST NOT have more than one active ordinary physical Attempt at a time. Any NodeType that intentionally models parallel speculative Attempts requires an explicit future contract; ordinary retry/resume is sequential.

### R7. Runtime identity

Canonical execution MUST call ExecutionRuntime with `execution_id = Attempt.attempt_id`, never the logical `run_id`.

### R8. Runtime deadline classification

Runtime-owned deadline expiry MUST terminalize the Attempt as `timed_out`. An executor independently raising `TimeoutError` MUST NOT be classified as Runtime deadline expiry merely because its exception type is `TimeoutError`.

### R9. Cancellation persistence

When Runtime cancellation completes, Attempt MUST be persisted terminal before or as part of NodeRun/Run reconciliation. A successful cancellation path MUST NOT leave durable logical records indefinitely `running` with no physical worker.

### R10. Recovery reconciliation

On startup/recovery, a non-terminal Run/NodeRun whose latest Attempt is terminal or stale and has no valid active worker MUST be reconciled according to recovery policy rather than assumed active.

### R11. Waiting/paused semantics

A waiting/paused Run or NodeRun MUST be persistable without a live execution coroutine/process.

### R12. Child Runs

Child Runs MUST store `parent_run_id`; when created for a Node delegation/subgraph they SHOULD also store `parent_node_run_id`.

A child Run defaults to its parent's Project. Explicit cross-Project child creation MAY target another Project only inside the same Workspace and only after authorization approves the destination. Cross-Workspace child creation MUST be rejected.

### R13. Queue separation

A WorkRequest/queue item MAY exist before a Run. Once accepted/admitted, externally authoritative workload lifecycle MUST transition to canonical Run rather than remain solely in TaskStatus.

### R14. Scheduler separation

A Schedule trigger MUST create/resume a Run. Scheduler records MAY reference Run but MUST NOT own a competing post-admission lifecycle.

### R15. Durable convergence

Existing durable Run/Node records MAY remain during migration but MUST become persistence projections/adapters of canonical Run/NodeRun semantics rather than separate authoritative definitions.

### R16. Canonical execution service boundary

Domain and product callers SHOULD enter universal execution through a canonical Run service that creates Run/NodeRun identity and routes physical work through Attempt -> ExecutionRuntime. That service MUST NOT own graph traversal, authorization, Provider selection, retry eligibility, scheduling, or Run-completion policy. Retrying physical work MUST be an explicit operation on the existing NodeRun rather than implicit creation of another logical NodeRun.

## Acceptance Criteria

```gherkin
Feature: Run / NodeRun / Attempt lifecycle

  @AC-1
  Scenario: Every allowed transition is covered, and illegal ones are refused
    Given the Run lifecycle state machine
    When each allowed transition is exercised
    Then it succeeds
    And a representative illegal transition and a transition out of a terminal state are both refused

  @AC-2
  Scenario: Run creation refuses a snapshot from another scope
    Given a declared Run scope
    When a Graph snapshot with a different workspace_id or project_id is supplied
    Then Run creation is rejected

  @AC-3
  Scenario: Policy retry keeps identity and adds an ordinal
    Given a failed Attempt under a Run and NodeRun
    When policy retries it
    Then the new Attempt has ordinal +1
    And the run_id and node_run_id are unchanged

  @AC-4
  Scenario: A stale resumable NodeRun resumes from its Checkpoint
    Given a resumable NodeRun whose Attempt went stale
    When recovery runs
    Then a new Attempt is created referencing that Checkpoint
    And no new Run is created

  @AC-5
  Scenario: Concurrent Attempts under one Run do not collide
    Given two Attempts of one Run dispatched concurrently
    When the Runtime is invoked for each with its attempt_id
    Then both execute with distinct execution IDs

  @AC-6
  Scenario: Runtime deadline expiry is recorded and reconciled
    Given an Attempt that exceeds the Runtime deadline
    When the deadline expires
    Then the Attempt is recorded as timed out
    And logical state is reconciled according to policy

  @AC-7
  Scenario: An executor TimeoutError is a failure, not a Runtime timeout
    Given an executor that raises TimeoutError
    When the Attempt runs
    Then the Attempt is recorded failed
    And it is reclassified only when domain policy says so explicitly

  @AC-8
  Scenario: Cancellation leaves no phantom running worker
    Given active work under an Attempt
    When it is cancelled
    Then the Attempt ends cancelled
    And NodeRun and Run state are reconciled
    And recovery finds no durable record of a running worker

  @AC-9
  Scenario: A wait survives restart with no live worker
    Given a NodeRun paused awaiting human approval
    When the process restarts with no live worker
    Then the wait is still pending
    And it resumes through a new Attempt

  @AC-10
  Scenario: A child Run inherits its parent Project
    Given a Run in a Project
    When a child Run is created with no destination specified
    Then the child records the parent's project_id

  @AC-11
  Scenario: Cross-Project child Runs are explicit and authorized
    Given a Run in one Project and a destination Project in the same Workspace
    When a child Run is created explicitly against the destination
    Then the child records the destination project_id
    And destination authorization was consulted

  @AC-12
  Scenario: Cross-Workspace child Run creation fails
    Given a Run in one Workspace
    When a child Run is created against a Project in another Workspace
    Then creation fails

  @AC-13
  Scenario: Accepting a WorkRequest produces a Run
    Given an accepted WorkRequest
    When it is admitted
    Then a Run exists for it
    And task/queue status reads as a projection of that Run rather than its own lifecycle

  @AC-14
  Scenario: A scheduled execution uses the same lifecycle service as a manual one
    Given a Schedule due to fire
    When it fires
    Then the Run is created through the same lifecycle service a manual execution uses

  @AC-15
  Scenario: Durable adapters preserve traversal semantics on canonical ids
    Given a Graph using conditional traversal, fanout/fanin, retries and pause/resume
    When it executes through the durable adapter
    Then every one of those behaviours is preserved
    And the execution is recorded against canonical Run, NodeRun and Attempt ids

  @AC-16
  Scenario: History reloads with identical relationships
    Given persisted Run, NodeRun and Attempt history
    When it is reloaded
    Then the logical and physical relationships are identical to those written

  @AC-17
  Scenario: A migrated entry path cannot complete work without a Run
    Given a migrated execution entry path
    When workload is submitted through it
    Then the workload cannot reach completion without a canonical Run

  @AC-18
  Scenario: The canonical execution service is independent of traversal and product code
    Given the canonical execution service
    When it executes one Node as Graph -> Run -> NodeRun -> Attempt -> ExecutionRuntime
    Then it does so without importing graph traversal, authorization, Binding/Provider selection, or product-specific lifecycle code
```

## Migration order

1. Project-scope identity on Graph/Run.
2. Attempt -> ExecutionRuntime service and terminal reconciliation.
3. Canonical Event + Checkpoint.
4. Graph/durable persistence convergence.
5. Queue/scheduler/delegation/HITL/harness convergence.
6. Builders/RSI/Evolve and remaining product entry paths.
7. Delete competing lifecycle authorities after parity tests.

## Non-goals

This SPEC does not define graph traversal, Project authorization algorithms, Provider selection, Event payload schemas, or retry eligibility policy.
