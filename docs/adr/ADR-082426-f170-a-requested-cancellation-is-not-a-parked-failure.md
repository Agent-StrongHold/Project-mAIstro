---
id: ADR-082426-f170
title: "A requested cancellation is not a parked failure, and the Attempt cannot say which it is"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-24
accepted: 2026-08-24
history:
  - status: Proposed
    date: 2026-08-24
  - status: Accepted
    date: 2026-08-24
substrate:
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-082426-a47f
  - maistro-engine#ADR-081426-1f7c
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082426-f170: A requested cancellation is not a parked failure, and the Attempt cannot say which it is

## Context

ADR-081226-a66b says cancellation, exception, deadline and success must each terminalize the
Attempt before logical reconciliation. They do. What it does not say is what each of them
means *logically*, and the reconciler had one answer for all of them but success.

Driving one node through `RunExecutionService.execute_node` with three executors differing
only in how they end:

```
cancel   -> raised CancelledError           attempt=cancelled  node_run=waiting  run=waiting
timeout  -> raised RuntimeDeadlineExceeded  attempt=timed_out  node_run=waiting  run=waiting
fail     -> raised RuntimeError             attempt=failed     node_run=waiting  run=waiting
```

The Attempt records the distinction faithfully; the logical records discard it.
`AttemptLifecycleReconciler.reconcile` had a single non-completed path — park the NodeRun,
then park the Run if nothing else is active — and every terminal-but-not-completed Attempt
went down it.

So on any record that counts NodeRuns, a user cancelling their own work looked exactly like
a provider being down. `WAITING` means "parked, awaiting a retry decision", and for the
cancellation that decision had already been made and was *don't*.

**The obvious fix is wrong.** Mapping `AttemptStatus.CANCELLED` to a cancelled NodeRun
breaks crash recovery. `graph/durable_runs/attempt_executor.py::_reconcile_orphaned_attempts`
cancels every `CREATED`/`RUNNING` Attempt it finds on resume — `error="orphaned physical
Attempt recovered after process loss"` — precisely so a *fresh* Attempt can run. That
cancellation wants the park: the node is still owed, and terminalizing it would make
recovery destroy the work it exists to resume.

One status, two meanings, and nothing in the persisted Attempt separates them.

## Decision

**1. The caller says which cancellation it is; the reconciler does not infer it.**

`reconcile()` takes a `CancellationCause` — `REQUESTED` or `RECOVERED` — read only for a
CANCELLED Attempt. Both call sites already know, unambiguously and locally:
`AttemptExecutionService`'s `except asyncio.CancelledError` is a request to stop;
`_reconcile_orphaned_attempts` is bookkeeping after process loss.

The alternative was a distinct physical status for recovery — an `ABANDONED` beside
`CANCELLED`. Rejected, and the cost is worth naming: `AttemptStatus` is canonical in
ADR-081226-a66b, so a new member changes the lifecycle every store, projection and
`quality/execution-lifecycles.json` entry agrees on, in order to record something that is
not a property of the physical try at all. *Why* an Attempt was cancelled is the caller's
knowledge, not the Attempt's state.

**2. It defaults to `RECOVERED`.**

The two mistakes are not symmetric. Defaulting to parked leaves a less informative record;
defaulting to terminal would make a caller that forgot to say destroy resumable work. The
default is the safe one, and the two call sites that matter both state their cause
explicitly rather than leaning on it.

**3. A requested cancellation terminalizes the NodeRun as `cancelled`, and the Run with it
when nothing else is live.**

Conditional for the same reason `_park_run_if_inactive` is: a sibling node still running
means the Run is still running, and one cancelled branch does not decide for the others.
`CANCELLED` rather than `WAITING` because a Run parked awaiting a decision already taken is
the defect ADR-082426-a47f removed one level up — and because the durable Graph executor
reached the same answer independently in `_persist_cancelled_run`.

**4. Timeout and failure keep parking.**

Both are plausibly retryable, and whether to retry is a policy decision belonging above this
layer — which is exactly what `WAITING` is for. Only cancellation is a decision already
taken. Stated here rather than left implied, because "all three park" was previously true by
accident rather than by choice.

## Consequences

### Positive

- A cancelled turn is distinguishable from an outage on every record that counts them, which
  is the difference between a dashboard that means something and one that does not.
- The reconciler keeps its policy-neutrality: it still does not decide whether anything is
  retryable, it is now *told* when the decision has already been made elsewhere.
- A cancelled NodeRun's `error` is its own Attempt's (`execution cancelled`) rather than the
  Run cascade's report of terminalization — the cause rather than one remove from it.

### Negative / Trade-offs

- **`reconcile()` grows a parameter that only matters for one of four statuses.** A caller
  passing `REQUESTED` for a failed Attempt is silently ignored rather than refused. Refusing
  it would push every caller into a conditional to describe a case it does not have.
- A default that is right for recovery is a default that is quietly wrong for any future
  request-cancelling caller that forgets to say so. The failure mode is a less informative
  record, not lost work, and that is the trade being made.

### Neutral

- `CancellationCause` has two members deliberately. It says why a cancellation happened, not
  what state anything is in, and `scripts/check-execution-lifecycles.py` classifies an enum
  as a lifecycle only at three or more work-state members — so this cannot become a second
  lifecycle by accident.
- The Attempt layer is untouched. What physically happened is unchanged; only its logical
  projection is now told apart.
