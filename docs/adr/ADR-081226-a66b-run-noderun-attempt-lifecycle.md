---
id: ADR-081226-a66b
title: Run, NodeRun and Attempt Lifecycle
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-69ee
  - maistro-engine#ADR-081426-1f7c
---

# ADR-081226-a66b: Run, NodeRun and Attempt Lifecycle

## Decision

MAIstro has one universal logical execution hierarchy:

```text
Run
└── NodeRun[]
    └── Attempt[]
        └── ExecutionRuntime
```

Run is one logical execution of an immutable Graph snapshot. NodeRun is one logical execution occurrence of one Node in that Run. Attempt is one physical try under a NodeRun.

Every Run carries immutable `workspace_id` and `project_id` scope copied from the captured Graph snapshot at Run creation. Moving the source Graph later does not move an existing Run.

Retry and recovery create new Attempts under the same logical NodeRun when that NodeRun remains logically resumable. A NodeRun has at most one active ordinary Attempt at a time.

Runtime `execution_id` is `Attempt.attempt_id`. Runtime reports mechanics outcomes; domain lifecycle services persist Attempt terminal state and reconcile NodeRun/Run state. Runtime does not directly terminalize business records.

## Child Runs

A child Run stores parent Run correlation and, when relevant, parent NodeRun correlation. It defaults to the parent Run's Project.

A child Run may explicitly target another Project only within the same Workspace and only after authorization permits Run creation/use in that destination scope. The child then resolves Project-scoped resources from its own destination Project. Parent/child relationships never provide implicit cross-Workspace authority.

## Lifecycle ownership

Run owns universal logical lifecycle. GraphExecutionState owns traversal-specific state. Queue items, Schedule records, delegation records, harness sessions, and durable persistence projections do not own competing universal post-admission lifecycles.

Canonical Run states are:

`created`, `queued`, `running`, `waiting`, `paused`, `completed`, `failed`, `cancelled`, `timed_out`.

Canonical Attempt physical outcomes include:

`created`, `running`, `completed`, `failed`, `cancelled`, `timed_out`, `yielded`.

Terminal state transitions are explicit and illegal transitions are rejected.

## Runtime outcome classification

Runtime-owned deadline expiry produces a timed-out Attempt. An executor independently raising `TimeoutError` is not automatically a Runtime timeout; it is a failed Attempt unless domain policy maps that failure differently.

Cancellation, exception, deadline, and success MUST terminalize the Attempt before or as part of logical reconciliation so recovery does not leave persisted `running` state after physical execution is gone.
