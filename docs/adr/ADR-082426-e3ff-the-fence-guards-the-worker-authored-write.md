---
id: ADR-082426-e3ff
title: "The fence guards the worker-authored write, and acceptance is one of them"
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
  - maistro-engine#ADR-081626-f383
implements: []
related:
  - maistro-engine#ADR-081226-a66b
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_spine_conformance.py
ac-modules:
  AC-1: maistro.runs.reconciliation
  AC-2: maistro.runs.reconciliation
  AC-3: maistro.runs.reconciliation
  AC-4: maistro.runs.reconciliation
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082426-e3ff: The fence guards the worker-authored write, and acceptance is one of them

## Context

ADR-081626-f383 establishes the execution lease and its fencing token so a stale physical
worker cannot overwrite a newer Attempt. #45 asks for that contract to hold "at every
mutating commit boundary".

It held at one. `_validate_fence` exists in all four store implementations — the reference,
SQLite, PostgreSQL and the durable-Graph adapter — and every one of them calls it from
`transition_attempt` alone. `transition_node_run` and `transition_run` accept no fencing
token at all.

So the physical record was guarded and the logical records it projects into were not.
Reproduced against the reference store: worker A completes an Attempt but has not yet
committed its outcome; recovery parks the node as orphaned; worker B claims Attempt 2 and is
live; worker A then commits.

```
attempt 2 is live under the same NodeRun (ordinal 2, holder worker-B)
STALE ACCEPTANCE LANDED -> node_run=completed result={'from': 'worker-A (stale)'}
```

`accept_outcome` already validated the outcome against the **persisted** Attempt, so forged
evidence was refused. That check is the wrong question for this failure: matching evidence
for a superseded Attempt is exactly what a stale worker holds.

## Decision

**1. Acceptance is a worker-authored write, and is fenced by currency.**

`accept_outcome` refuses an outcome whose Attempt is not the newest under its NodeRun,
raising `SupersededAttempt` naming both. Newest is decided by **ordinal**, because
`create_attempt` allocates ordinals under a row lock — the highest one is the Attempt that
most recently claimed the NodeRun, whatever order a given store returns rows in.

Currency rather than the fencing token itself: the token proves *which* Attempt a caller
holds, and the question here is whether that Attempt is still the current one. The token
would answer it only by first resolving the Attempt it belongs to, which is the same lookup
with an extra step.

**2. `transition_node_run` and `transition_run` are not fenced, and that is deliberate.**

They are **domain-authored** writes, not worker-authored ones. `TaskRunAdmitter.record_transition`
moves a Run because a task receipt moved; `Container._terminalize` because a chat turn
ended; the abandoned-stream path because an HTTP client hung up. None of those callers holds
a lease, none is racing another worker for the same Attempt, and threading a fencing token
through them would put lease mechanics in the task queue and the chat endpoint to describe a
contention that does not exist there.

The distinction that matters is not *which table* is being written but *who is writing*. A
worker committing what it produced must prove it is still the current worker. A domain
recording what it decided is the only writer of that decision.

**3. The durable Graph fold is out of scope here, and its exposure is stated rather than
assumed.**

`authoritative_fold.py` writes acceptance by calling the pure `transition_node_run(...,
accepted_outcome=...)` on its own checkpointed record, bypassing `accept_outcome` entirely.
Whether it needs the same currency check depends on the concurrency control of
`DurableRunStore`'s checkpoint, which this decision does not establish. Naming it as
unestablished is the point: it is the one remaining route by which an acceptance reaches a
NodeRun without passing this check.

## Acceptance Criteria

Each rule is asserted twice. The marked test runs against `InMemoryRunStore`,
which has no environment gate, so the criterion is measurable wherever the
suite runs; the identically-bodied conformance test runs the same assertions
against all three stores and carries the cross-store claim in CI's postgres
legs. The assertions live once, in a shared helper, so the two cannot drift.

The split is not decoration. `scripts/ac_outcome_plugin.py` treats a skip as no
evidence — "an environment-gated test that never ran is not evidence the
criterion holds" — and the Quality gate job configures no database, so marking
the parameterized tests would pin every criterion below at `covered` forever.

- [x] **AC-1**: A worker whose Attempt has been superseded cannot commit an
  outcome. `accept_outcome` raises `SupersededAttempt`, naming the Attempt that
  superseded it, and the NodeRun is left untouched.
- [x] **AC-2**: The current worker is unaffected — including the
  `prior_completion_accepted` continuation path, which re-runs after an
  accepted completion under a new Attempt and is exactly what the
  newest-ordinal rule keeps working.
- [x] **AC-3**: "Newest" is decided by `ordinal`, not by the order the store
  happens to return rows in. A store that listed Attempts oldest-last would
  otherwise pass this suite while fencing nothing.
- [x] **AC-4**: The pre-existing evidence check still runs first: a forged
  result is refused as a forgery, not misreported as a supersession.

## Consequences

### Positive

- #45's "stale-write tests fail closed" becomes true at the boundary a stale worker actually
  reaches, on all three run stores.
- The two refusals stay distinguishable. Forged evidence raises `RunIntegrityError` about
  evidence; a superseded Attempt raises `SupersededAttempt`. They mean different things and a
  caller retries differently — the first is a bug, the second is a race it lost.

### Negative / Trade-offs

- **`accept_outcome` costs one extra read.** `list_attempts` on every acceptance, and
  `AttemptLifecycleStore` grows that method to require it. Every implementation already had
  it via `AttemptExecutionStore`, so no store changed — but the protocol is wider, and a
  future store must now provide it to reconcile at all.
- A domain that legitimately wants to accept an older Attempt's result has no way to say so.
  Nothing wants that today, and the continuation path that comes closest —
  `prior_completion_accepted` — re-runs *after* an acceptance rather than accepting a
  superseded one.

### Neutral

- This closes a fail-open contract on a library surface, not a live incident.
  `accept_outcome` has no in-repo production caller: it is the deferred-acceptance half of
  `reconcile_logical=False`, and the one domain that defers acceptance takes the Graph route
  in decision 3. Fixing it before a caller arrives is cheaper than after, and the honest
  framing is preventive.
- It is a second instance of the shape #236 describes: a public surface whose safety nobody
  exercised, because nobody called it.
