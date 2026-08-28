---
id: ADR-082826-08f0
title: "Interrupted-Run recovery has one disposition table, keyed on proven liveness"
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
  - maistro-engine#ADR-082526-b36a
  - maistro-engine#ADR-082426-f170
  - maistro-engine#ADR-082426-a47f
  - maistro-engine#ADR-081626-f383
  - maistro-engine#ADR-082326-c126
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py
  - packages/maistro-core/tests/test_container_wiring.py
  - packages/maistro-core/tests/test_container_chat_runs.py
ac-modules:
  AC-1: maistro.graph.durable_runs.attempt_executor
  AC-2: maistro.graph.durable_runs.attempt_executor
  AC-3: maistro.graph.durable_runs.attempt_executor
  AC-4: maistro.graph.durable_runs.attempt_executor
  AC-5: maistro.container
  AC-6: maistro.container
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082826-08f0: Interrupted-Run recovery has one disposition table, keyed on proven liveness

## Context

M1 requires canonical crash recovery, but the repository grew six independent
answers to "what happens to persisted non-terminal work after an
interruption": the durable Graph resume assumed restart-implies-death and
cancelled every active Attempt with no liveness check; the lease sweep proved
death via a lapsed `ExecutionLease` but then settled only the Attempt, leaving
its NodeRun and Run `RUNNING` forever; process shutdown terminalized a chat
Run `CANCELLED` in one module and asked the task receipt to go `FAILED` in
another; chat admission could strand a `QUEUED` Run when the write after it
failed; and two products performed no recovery at all. Different producers
could therefore make contradictory restart decisions over the same canonical
Run/NodeRun/Attempt model (#462), which is the exact failure the canonical
spine exists to remove.

The evidence that already existed pointed one way. ADR-082526-b36a
established that liveness is proven, not assumed — a lapsed lease reclaims,
no lease means never reclaimed by a sweep — and rejected restart-implies-death
in the abstract, but the Graph resume path was never amended to honor it.
ADR-082426-f170 established the two meanings of a cancelled Attempt
(`REQUESTED` terminalizes, `RECOVERED` parks). ADR-082426-a47f established
the cascade when a Run terminalizes. What was missing was the one table that
composes them.

## Decision

Recovery of persisted non-terminal work follows **one disposition table**,
keyed on the persisted state and the liveness evidence available — never on
which producer happens to be looking:

| Persisted pre-interruption state | Liveness / fence evidence | Disposition |
|---|---|---|
| Run `CREATED`/`QUEUED`, admission incomplete, admitter still in-process | admitter's own failure | **Compensate**: cancel with the sanitized `admission_incomplete` category (#338). Nothing failed; the work was never dispatched. |
| Run `CREATED`/`QUEUED`, admitting process died | none available | **Owned by the recovery tick**: visible in `non_terminal_run_stats` and aged on the `maistro_non_terminal_runs` / `maistro_oldest_non_terminal_run_age_seconds` gauges until a sweep or operator disposes of it. Silent disappearance is not a disposition. |
| Attempt `CREATED`/`RUNNING` with a **live** lease (`expires_at` in the future) | lease is the proof of life | **Refuse recovery.** No other process may steal, terminalize, or re-dispatch demonstrably owned work: the fence stops a stale worker's *write*, not a duplicate *execution*, so the refusal is the only thing that prevents double-dispatch. Durable Graph resume raises rather than proceeding. |
| Attempt `CREATED`/`RUNNING` with a **lapsed** lease | lease expiry | **Reclaim through the lease seam** (`reclaim_expired_attempts` — the one write the fence exempts, because a lapsed lease is its own authority), then reconcile with `CancellationCause.RECOVERED`: Attempt `CANCELLED` naming the holder, NodeRun parked `WAITING`, Run parked when nothing else is live. Retry rotates to a new Attempt and a new lease. |
| Attempt `CREATED`/`RUNNING`, **no lease**, under an explicit resume of the owning record | the resume itself asserts the process is gone; leaseless work cannot outlive its process | **Recover as orphaned**: cancel via `transition_attempt` (no fence to trip), reconcile `RECOVERED`, park, re-dispatch a fresh chronological Attempt. |
| Attempt `CREATED`/`RUNNING`, no lease, seen only by a sweep | none | **Never reclaimed** (b36a unchanged): a sweep that cannot prove death does not infer it. |
| NodeRun `WAITING`/`PAUSED` (parked, incl. HITL) | n/a | **Park is the disposition.** Terminal writes require the pending decision first; a paused HITL Run refuses resume until answered. |
| Requested cancellation (a person or policy said stop) | n/a | **Terminalize** (`REQUESTED` → `CANCELLED` cascades per f170/a47f) — never parked as if it were a retryable failure. |
| Run already terminal | n/a | **Refuse recovery.** History is never rewritten; repeated recovery of settled state is a no-op. |

Three rules bind every row:

1. **Recovery completes through the canonical lifecycle seam** — the
   `AttemptLifecycleReconciler` — never by editing Run/NodeRun rows
   independently. The lease sweep (`Container.recover_abandoned_attempts`)
   now reconciles what it reclaims; an Attempt settled without its logical
   records is half a disposition.
2. **Repeated recovery is idempotent.** Every row reaches a fixed point:
   parked stays parked, terminal stays terminal, and no path duplicates an
   Attempt or rewrites a historical outcome.
3. **Producers consume this table; they do not vote.** Task, chat, Graph,
   scheduler, and product code map their interruption onto a row. A producer
   that needs a new disposition amends this table first.

## Acceptance Criteria

- **AC-1**: Resuming a durable Graph whose active Attempt holds a live
  execution lease is refused; the Attempt, its NodeRun, and the Run are left
  untouched and no duplicate physical execution is dispatched.
- **AC-2**: Resuming past a lapsed lease settles the Attempt through the
  lease seam (`reclaim`), parks and re-dispatches through the canonical
  reconciler, and the Run completes on a fresh chronological Attempt.
- **AC-3**: Running orphan reconciliation twice over the same interrupted
  record reaches the same state: one cancelled Attempt, a parked NodeRun, a
  parked Run — nothing duplicated, nothing rewritten.
- **AC-4**: A restart mid-Attempt against a durable (SQLite) store, across a
  real store reopen, produces the documented disposition: the interrupted
  Attempt's history preserved as `CANCELLED`, a fresh Attempt with the next
  ordinal, and a `COMPLETED` Run.
- **AC-5**: The lease-recovery tick completes reclaim through the
  `AttemptLifecycleReconciler` — the reclaimed Attempt's NodeRun parks
  `WAITING` and its Run parks — and refreshes the non-terminal-Run count and
  oldest-age gauges; a second tick reclaims nothing and rewrites nothing.
- **AC-6**: A chat admission that fails after persisting a pre-`RUNNING`
  state compensates the Run to `CANCELLED` with the sanitized
  `admission_incomplete` category while still answering the turn, and
  repeated compensation never rewrites a settled Run.

## Consequences

### Positive

- A resume can no longer cancel an Attempt out from under a live, renewing
  worker and double-dispatch its work — the one genuinely dangerous
  contradiction between restart-implies-death and lease-implies-death.
- A reclaimed Attempt's NodeRun and Run park instead of claiming to run
  forever, making b36a's promise true in code and the parked work visible to
  retry policy.
- Stranded admission is compensated at the seam that created it, and the
  crash-window residue is measured (`non_terminal_run_stats` + gauges) rather
  than invisible.
- The table gives #62 (checkpoint/recovery convergence) its policy input
  instead of leaving each recovery surface to re-derive one.

### Negative / Trade-offs

- A resume of a record whose worker is alive now fails loudly instead of
  proceeding; callers must retry after the lease lapses. That is the point,
  but it is a behavior change for any caller that relied on stealing.
- The leaseless-under-resume row still trusts the resumer's assertion of
  process death. With single-process leaseless executors that assertion is
  sound by construction; distributed leaseless execution remains forbidden
  rather than solved (that is #79's composition work, M2).
- The "admitting process died" row is owned by visibility plus operator
  sweep, not yet by an automatic disposer; full-scan healing belongs to #62.

### Neutral

- `CancellationCause` deliberately keeps its two members. Reclaim and orphan
  recovery are both `RECOVERED`; the distinguishing detail (holder, cause)
  lives in the Attempt's error text, which is a record for people, not a
  branch for code.
- Shutdown semantics (`CANCELLED` from the runtime vs the task runner's
  `FAILED` receipt ask) are reconciled by this table in favor of `REQUESTED`
  cancellation; the task-receipt refusal path is tracked separately and does
  not decide lifecycle.
