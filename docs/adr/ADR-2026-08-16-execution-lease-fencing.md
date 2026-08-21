---
id: ADR-081626-f383
title: Canonical Attempt Execution Lease and Fencing Contract
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-16
contracts:
  - behavioral
  - boundary
  - cross-service
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# Canonical Attempt Execution Lease and Fencing Contract

## Context

The canonical execution spine separates logical execution identity from physical execution mechanics:

```text
Run
└── NodeRun
    └── Attempt
        ↓
   ExecutionRuntime
```

A `NodeRun` is one logical visit/execution. An `Attempt` is one physical try under that logical identity. Process loss, recovery, timeout handling, and retry can cause more than one physical worker to believe it owns the same logical work unless persistence provides an explicit execution authority token.

The unsafe race is:

1. Attempt 1 begins on worker A.
2. worker A appears dead or loses ownership.
3. recovery creates Attempt 2 on worker B.
4. worker A later reports completion.
5. without fencing, stale completion can overwrite or compete with the newer physical execution.

## Decision

Production `AttemptExecutionService` executions acquire a durable `ExecutionLease` when the `Attempt` is created.

```text
NodeRun
  ↓
Attempt + ExecutionLease
  ↓
ExecutionRuntime
  ↓
fenced Attempt transition
```

The lease contains:

- `node_run_id`
- `attempt_id`
- monotonic `lease_epoch`
- `holder_id`
- opaque `fencing_token`
- `issued_at`
- optional `expires_at`

Every state mutation made by a leased physical execution must present the matching fencing token. A missing, wrong, or superseded token is rejected as `StaleExecutionFence`.

Retries advance the lease epoch and receive a new fencing token. Earlier tokens therefore cannot control a newer physical Attempt.

Low-level persistence fixtures may continue to create unfenced Attempts when no lease holder is requested. This preserves storage compatibility while keeping production execution explicitly fenced.

## Ownership

The canonical Run store owns lease identity and fencing enforcement because the fence protects authoritative Attempt persistence. `ExecutionRuntime` consumes execution authority but does not mint or persist it.

`AttemptExecutionService` is responsible for requesting the lease and carrying its fencing token across physical state transitions.

## Current boundary

This contract establishes durable execution authority and stale-writer rejection. It intentionally does not yet define lease-expiry takeover or recovery-driven supersession of an apparently live Attempt. Those behaviors require explicit reclaim authority and failure classification rather than implicit timeout assumptions.

Until that later contract lands, the existing one-active-Attempt invariant remains authoritative.

## Consequences

- physical workers cannot update a leased Attempt without proving current execution authority;
- retries create monotonically newer lease epochs;
- stale fencing tokens cannot control later Attempts;
- in-memory and SQLite stores enforce the same contract;
- recovery/failover can later build reclaim semantics on an explicit durable primitive rather than process-local locks.
