---
id: ADR-081426-1f7c
title: ExecutionRuntime Contract
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-14
accepted: 2026-08-14
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-14
  - status: Accepted
    date: 2026-08-14
related:
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081226-69ee
---

# ADR-081426-1f7c: ExecutionRuntime Contract

## Decision

ExecutionRuntime is MAIstro's substitutable mechanics boundary for one physical execution. Its `execution_id` is the canonical Attempt ID.

ExecutionRuntime owns mechanics only:

- bounded concurrency and capacity waiting,
- cancellation propagation,
- execution deadlines,
- asynchronous task/process lifecycle mechanics,
- runtime event sequencing mechanics,
- runtime health and mechanics metrics,
- backpressure/process supervision hooks where implemented.

ExecutionRuntime MUST treat work items, execution context, and emitted domain payloads as opaque. It MUST NOT interpret Graph traversal, Run/NodeRun lifecycle meaning, permissions, retry policy, Provider selection, delegation semantics, scheduling semantics, business results, or persistence policy.

Python remains authoritative for product/domain semantics. A future native implementation may replace proven hot mechanics behind this contract, but it cannot become the source of truth for MAIstro domain behavior.

## Attempt identity

A logical Run can contain concurrent NodeRuns and Attempts. Therefore physical runtime identity MUST be `Attempt.attempt_id`, not `Run.run_id`.

```text
NodeRun
-> create Attempt
-> Attempt running
-> ExecutionRuntime.execute(execution_id=attempt_id)
-> result / exception / cancellation / deadline
-> domain service terminalizes Attempt
-> domain service reconciles NodeRun
-> domain service reconciles Run
```

Runtime never directly terminalizes persisted business objects.

## Deadlines

A Runtime deadline covers the entire physical execution request, including time waiting for bounded-concurrency capacity.

Runtime-owned deadline expiry MUST be distinguishable from an executor or downstream dependency independently raising `TimeoutError`. Only expiry of the Runtime's own deadline is a Runtime timeout metric/outcome. An executor-raised timeout is an executor failure unless domain policy classifies it otherwise.

The public API SHOULD surface a dedicated Runtime deadline exception while remaining catchable as `TimeoutError` for ordinary timeout handling.

## Slot accounting

The public slot-acquisition primitive owns capacity-wait and peak-concurrency accounting. Code using the lower-level Runtime slot API must produce metrics equivalent to code using `execute()`.

An execution ID may be neither a duplicate waiter nor a duplicate holder. Cancellation or deadline expiry while waiting for capacity MUST NOT leak a semaphore slot.

## Runtime event sequencing

Runtime may assign monotonic mechanics sequence numbers to opaque events. It MUST NOT await arbitrary event-sink callbacks while holding the sequencing lock. Event-sink callbacks may recursively emit another event without deadlocking.

This mechanics sequence is not the durable canonical Event model. Durable product Event sequencing and persistence are a separate domain service.

## Benchmarking

Runtime benchmark workload time ends when the measured execution workload completes. Optional lag samplers or observability sampling that continue after workload completion MUST NOT inflate workload wall time or reduce reported throughput.

## Consequences

Attempt-to-Runtime integration can classify mechanics outcomes precisely without teaching Runtime business lifecycle semantics. The public contract is small enough to support a future Python/native implementation choice while preventing graph/runtime architecture from collapsing back together.
