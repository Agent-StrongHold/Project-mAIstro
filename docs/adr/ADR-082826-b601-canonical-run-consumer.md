---
id: ADR-082826-b601
title: "A canonical consumer executes admitted Runs that no caller drives"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-28
accepted: 2026-08-28
history:
  - status: Proposed
    date: 2026-08-28
  - status: Accepted
    date: 2026-08-28
substrate: []
implements: []
related:
  - maistro-engine#ADR-082126-f69c
  - maistro-engine#ADR-082526-237d
  - maistro-engine#ADR-081226-a66b
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_consumption.py
  - packages/maistro-core/tests/scheduling/test_admission.py
ac-modules:
  AC-1: maistro.container
  AC-2: maistro.container
  AC-3: maistro.container
  AC-4: maistro.container
  AC-5: maistro.scheduling.admission
  AC-6: maistro.runs.store
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082826-b601: A canonical consumer executes admitted Runs that no caller drives

## Context

Every work producer admits a canonical Run (#41, ADR-082126-f69c), but only
two producers ever executed theirs: the task queue drives its Runs through a
runner holding the receipt, and a chat turn executes inline in the request
that admitted it. A schedule Run has neither shape — its admission *is* its
submission — and `ScheduleRunAdmitter` therefore admitted canonical Runs that
nothing anywhere executed. That is the precise failure #251 names: do not
admit a Run nobody executes. The recurrence ADR's own status table claimed
fires produce canonical Runs "via `services/dag_agents.py`", which produces
in-memory `DurableRunRecord`s instead — canonical admission existed, canonical
execution did not.

The canonical `RunStore` also had no way to *find* admitted work: its only
status-aware query was an aggregate. The disjoint `DurableRunStore` already
carried `list_by_status`, so the two stores were diverging on query surface.

## Decision

1. **One consumer, tick-shaped.** `Container.execute_admitted_runs` is the
   canonical consumer: bounded, idempotent, operator-scheduled, never
   self-starting (ADR-019), beside `process_durable_events` and
   `recover_abandoned_attempts`. Products schedule the tick; the library
   never starts work on import.
2. **Eligibility is opt-in, never inferred.** The tick claims a Run only when
   it is `QUEUED`, its `admission_source` is in the consumer allowlist
   (`CONSUMABLE_SOURCES`, initially `schedule`), and its Graph is a single
   registered node. `CREATED` is never eligible: it is a legitimate resting
   state for Runs that must not execute here — a delegation child is a
   projection (ADR-082426-6201), and an unvetted run_id must stay untouched.
   A source joins the allowlist by amending it in one reviewed place, never
   by having its Runs picked up as a side effect of being non-terminal.
3. **The claim is the lifecycle transition.** A tick claims a Run with
   `QUEUED → RUNNING`; the transition table is the mutex, so a concurrent
   tick's loser skips rather than double-executing. No second claim
   mechanism, no consumer-owned lock table.
4. **Execution goes through the one spine.** `ScheduleAttemptExecutor` drives
   the node through `RunExecutionService` — canonical NodeRun and Attempt,
   Run terminal state derived from the NodeRun (ADR-082526-237d), never
   asserted by the consumer. A failed physical try parks (`WAITING`) per the
   recovery disposition; the next tick does not invent a retry decision.
5. **Admission queues in the same insert.** `ScheduleRunAdmitter` admits with
   `initial_status=QUEUED`: there is no later caller whose submission the
   `CREATED → QUEUED` hop would represent, and the single insert leaves no
   two-commit stranding window.
6. **`RunStore.list_by_status` is the discovery surface**, mirrored from
   `DurableRunStore.list_by_status` on all three backends, oldest first so a
   bounded tick drains a backlog fairly.

Multi-node Runs are out of the consumer's scope by design: traversal belongs
to the durable Graph execution path, and bridging a canonically admitted
`run_id` into `run_durable_graph(run_id=…)` is that convergence's seam
(#44/#34), not this one's. Until then a multi-node admitted Run stays
`QUEUED` and visible, never half-executed.

## Acceptance Criteria

- **AC-1**: An admitted single-node schedule Run is executed by the consumer
  tick to `COMPLETED`, leaving one canonical NodeRun and one Attempt, with
  the Run's terminal state derived from the NodeRun and the schedule's
  configured inputs reaching the node.
- **AC-2**: `CREATED` Runs, Runs from non-allowlisted sources, and multi-node
  Runs are never claimed: the tick leaves their status and record history
  exactly as admitted.
- **AC-3**: A scheduled node that fails parks its NodeRun and Run `WAITING`
  with the failure on the Attempt, and the next tick does not re-execute
  parked work.
- **AC-4**: Two concurrent ticks execute one admitted Run exactly once — the
  `QUEUED → RUNNING` transition is the claim — and a drained backlog makes
  the tick a no-op.
- **AC-5**: `ScheduleRunAdmitter` admits the Run `QUEUED` in the same insert
  that creates it.
- **AC-6**: `RunStore.list_by_status` returns only the requested status,
  oldest first, bounded by `limit`, on the reference store and the durable
  backends.

## Consequences

### Positive

- The schedule producer's loop is closed: admitted work executes through the
  same NodeRun/Attempt spine as tasks and chat, and #231 can move the live
  Hive scheduler onto `ScheduleRunAdmitter` knowing its Runs will run.
- The claim/discovery surface (`list_by_status` + transition-as-mutex) is the
  reusable half: the next producer joins by allowlisting a source, not by
  building a fourth execution idea.

### Negative / Trade-offs

- The consumer executes single-node Runs only; a multi-node schedule template
  admits work the tick will not touch. That is visible (QUEUED, aged on the
  recovery gauges) rather than hidden, and owned by the durable-graph
  convergence.
- An allowlist means a new producer's Runs sit QUEUED until someone amends
  one frozen set. That friction is the point — it is the reviewed moment a
  source opts into being executed by something other than itself.

### Neutral

- Product wiring (which process runs the tick, on what cadence) is the
  product's decision, tracked by #231 for Hive; this ADR fixes only what the
  tick does when run.
