---
id: SPEC-081426-1f7c
title: ExecutionRuntime Contract
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-14
history:
  - status: Proposed
    date: 2026-08-14
  - status: Accepted
    date: 2026-08-14
  - status: AC Defined
    date: 2026-08-14
substrate:
  - maistro-engine#ADR-081426-1f7c
implements:
  - maistro-engine#ADR-081426-1f7c
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
  - packages/maistro-core/src/maistro/runtime
ac-modules:
  AC-1: maistro.runtime.execution
  AC-2: maistro.runtime.execution
  AC-3: maistro.runtime.execution
  AC-4: maistro.runtime.execution
  AC-5: maistro.runtime.execution
  AC-6: maistro.runtime.execution
  AC-7: maistro.runtime.execution
  AC-8: maistro.runtime.execution
  AC-9: maistro.runtime.execution
  AC-10: maistro.runtime.execution
  AC-11: maistro.runtime.execution
  AC-12: maistro.graph.durable_runs.attempt_executor
  AC-13: maistro.runtime.execution
  AC-14: maistro.runtime.execution
  AC-15: maistro.runtime.execution
  AC-16: maistro.runtime.execution
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081426-1f7c: ExecutionRuntime Contract

- **Status:** Active
- **Date:** 2026-08-14
- **ADR:** `ADR-081426-1f7c`

## Public contract

The Runtime implementation MUST expose mechanics equivalent to:

```text
execute(work_item, execution_context, execution_id, executor, timeout?)
cancel(execution_id)
acquire_slot(execution_id)
release_slot(execution_id)
emit(opaque_event)
metrics()
health()
```

`execution_id` identifies one physical Attempt.

## Requirements

### R1. Opaque domain inputs

Runtime MUST NOT import or interpret Graph predicates, Run/NodeRun lifecycle state, Permission/Policy meaning, Binding/Provider selection, scheduling rules, delegation rules, or durable persistence semantics.

### R2. Attempt identity

Canonical callers MUST pass `Attempt.attempt_id` as Runtime `execution_id`. Concurrent Attempts in one logical Run MUST be independently addressable and cancellable.

### R3. Bounded concurrency

Runtime MUST enforce configured bounded concurrency. Capacity waiting MUST be cancellable and deadline-bound. Slot acquisition/release MUST remain balanced through success, failure, cancellation, and deadline expiry.

### R4. Duplicate execution IDs

An `execution_id` already active, waiting for a slot, or holding a public slot MUST NOT begin a duplicate physical execution or acquire a second slot.

### R5. Deadline scope

When `timeout_s` or equivalent Runtime deadline is configured, the deadline MUST include time waiting for execution capacity and time executing the workload.

### R6. Deadline classification

Runtime-owned deadline expiry MUST surface a distinct Runtime deadline signal, preferably `RuntimeDeadlineExceeded`, that remains a `TimeoutError` subtype. Only that signal increments Runtime timeout metrics.

If the executor independently raises `TimeoutError`, Runtime MUST propagate it as an executor failure and MUST NOT classify it as Runtime deadline expiry.

### R7. Cancellation

`cancel(execution_id)` MUST cancel both slot-waiting and actively executing work when it remains cancellable. Cancellation MUST not leak capacity. Runtime records mechanics cancellation only; persisted Attempt/NodeRun/Run terminalization belongs to the domain service.

### R8. Public slot metrics

`acquire_slot()` itself MUST record scheduling wait and peak-concurrency metrics. A caller using `acquire_slot`/`release_slot` directly MUST receive correct mechanics metrics without needing to call `execute()`.

### R9. Event lock safety

Runtime sequence allocation MUST be monotonic for successful allocations. Runtime MUST release the sequencing lock before awaiting arbitrary event-sink code. A sink that recursively calls `emit()` MUST not deadlock.

### R10. Event sink failure

An event-sink exception MAY propagate to the emitter, but MUST NOT leave the sequence lock held or corrupt Runtime capacity state. Durable event delivery guarantees are outside this Runtime contract.

### R11. Benchmark lifetime

Runtime benchmark `wall_seconds` MUST measure execution workload completion, excluding any optional sampler shutdown that occurs afterward. Throughput MUST use that workload lifetime.

### R12. Health and metrics

Runtime health/metrics MAY expose mechanics such as active executions, active slots, peak concurrency, scheduling wait, cancellation/failure/timeout counts, event sequence, loop lag, CPU, and RSS. These are telemetry and MUST NOT become authoritative Run lifecycle state.

### R13. Pause classification

An execution that stops deliberately rather than finishing or failing MUST surface a distinct Runtime pause signal, preferably `ExecutionPaused`. Only that signal increments Runtime pause metrics, and it MUST increment neither the failure nor the completion count: a pause is not a failure, and counting it as a completion would trade an undercount of successes for an overcount and lose how much of the workload is parked.

The pause signal is defined by Runtime and carries no domain meaning. Why the work paused, what it waits on and when it resumes are domain facts, carried on a domain subclass; R1 and AC-10 forbid Runtime importing the domain to learn them. Runtime re-raises the signal so the domain service can terminalize the Attempt, exactly as it re-raises a failure.

## Acceptance Criteria

```gherkin
Feature: ExecutionRuntime contract

  @AC-1
  Scenario: Concurrent Attempts get distinct execution IDs
    Given two Attempts under one Run
    When both execute concurrently
    Then each holds a distinct execution ID

  @AC-2
  Scenario: Configured concurrency is never exceeded
    Given a Runtime configured for a fixed concurrency
    When more executions are submitted than slots exist
    Then the number running at once never exceeds the configured limit

  @AC-3
  Scenario: A deadline while queueing leaks no slot
    Given a Runtime with one slot, already held
    When a second request waits past its deadline
    Then the Runtime deadline signal is raised
    And capacity returns to its prior value with no slot leaked

  @AC-4
  Scenario: An executor TimeoutError is counted as a failure
    Given an executor that raises TimeoutError inside its slot
    When the execution completes
    Then failure metrics increment
    And Runtime-timeout metrics do not

  @AC-5
  Scenario: Cancellation while queueing leaves state consistent
    Given a request waiting for a slot
    When it is cancelled
    Then holder and waiter state contain no trace of it
    And semaphore capacity is unchanged

  @AC-6
  Scenario: A duplicate execution ID is rejected without consuming capacity
    Given an execution ID already held or waiting
    When the same ID is submitted again
    Then it is rejected
    And no capacity is consumed

  @AC-7
  Scenario: Direct slot acquisition still records metrics
    Given the public slot-acquisition API
    When a slot is acquired directly
    Then scheduling-wait and peak-concurrency metrics are recorded

  @AC-8
  Scenario: Recursive emission from a sink does not deadlock
    Given a sink that emits again while handling an event
    When the nested emit occurs
    Then both complete
    And their sequence numbers increase

  @AC-9
  Scenario: A throwing sink does not block later emits
    Given a sink that raises on one event
    When a later event is emitted
    Then that emit still reaches the sink

  @AC-10
  Scenario: Runtime does not depend on traversal or Run persistence
    Given the Runtime source
    When its imports are inspected
    Then it imports neither Graph traversal nor canonical Run persistence modules

  @AC-11
  Scenario: The benchmark stops timing at execution completion
    Given the Runtime benchmark with lag sampling active
    When workload execution completes
    Then reported workload timing ends there rather than continuing with the sampler

  @AC-12
  Scenario: Runtime execution_id comes from Attempt.attempt_id
    Given the canonical Attempt execution service
    When it invokes the Runtime
    Then the Runtime execution_id is the Attempt's attempt_id

  @AC-13
  Scenario: A deliberate pause increments the pause count
    Given an executor that raises the Runtime pause signal
    When the execution ends
    Then Runtime pause metrics increment

  @AC-14
  Scenario: A pause is not a failure
    Given an executor that raises the Runtime pause signal
    When the execution ends
    Then failure metrics do not increment

  @AC-15
  Scenario: A pause is not a completion
    Given an executor that raises the Runtime pause signal
    When the execution ends
    Then completion metrics do not increment

  @AC-16
  Scenario: A genuine error is still a failure
    Given an executor that raises an error that is not the pause signal
    When the execution ends
    Then failure metrics increment
    And pause metrics do not
```

## Non-goals

This SPEC does not define Run state transitions, retry eligibility, Graph traversal, Event durability, Provider fallback, or policy evaluation.
