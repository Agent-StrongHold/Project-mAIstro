---
id: ADR-082526-b36a
title: "A lease that stops being renewed is reclaimed; liveness is proven, not assumed"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-081626-f383
implements: []
related:
  - maistro-engine#ADR-082426-f170
  - maistro-engine#ADR-082426-e3ff
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_spine_conformance.py
ac-modules:
  AC-1: maistro.runs.lifecycle
  AC-2: maistro.runs.lifecycle
  AC-3: maistro.runs.lifecycle
  AC-4: maistro.runs.store
  AC-5: maistro.runs.lifecycle
  AC-6: maistro.runs.lifecycle
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-b36a: A lease that stops being renewed is reclaimed; liveness is proven, not assumed

## Context

#143 moved task execution onto `RunExecutionService` and named one case it did not close:

> A task Run whose executor never runs (queue drained at shutdown, worker died) must not leave
> a non-terminal Attempt behind.

PR #199 deferred that to #132; #132 landed PostgreSQL durability and retention and did not add
it. So a worker that dies after its Attempt is persisted `RUNNING` leaves durable state
claiming work is executing after the executor is gone, and `runs/reconciliation.py` cannot
help — it only accepts Attempts that are *already terminal*.

Two things were already true and shaped the answer.

**The liveness field existed and was never written.** `ExecutionLease` (ADR-081626-f383)
carries `expires_at`, validated against `issued_at`, and nothing in production ever set it.

**The durable Graph executor's orphan rule is not reusable.**
`_reconcile_orphaned_attempts` terminalizes every active Attempt found at resume. That is
sound for a graph Run, which has exactly one resumer. Applied to a multi-worker task queue it
would let any restarting worker cancel every other worker's live Attempt.

## Decision

**An Attempt may carry a lease TTL. A holder keeps it by renewing. A lease that lapses is
reclaimed.**

### Liveness is proven, not inferred

`reclaim_expired_attempts` settles only Attempts whose lease expiry has passed. Renewal —
`renew_lease(attempt_id, fencing_token=…, ttl=…)` — is how a holder proves it is still there.

Restart-implies-death was rejected: it is what the Graph does, and it is unsafe here for the
reason above. A bare TTL with no renewal was rejected too, and this is the subtler one: it
cannot distinguish a dead worker from a slow one, so a long-running healthy Attempt would be
reaped. `Attempt.deadline_at` cannot stand in either — overrunning a deadline is not dying,
and conflating them would make every slow task look like a crash.

**Renewal cadence is the caller's, and should be roughly TTL/3.** Two missed renewals then
lapse the lease, which tolerates one lost tick without reaping live work. The engine does not
enforce a ratio: the right TTL for a 200 ms tool call and a 40-minute build are different, and
a single constant would be wrong for both.

### Renewal keeps the same fencing token

Epoch, holder and token are unchanged by renewal. Renewal proves the *existing* holder is
alive; it is not a new claim. Minting a new token would invalidate the fence its own holder is
carrying (ADR-082426-e3ff) — the holder would be locked out by the act of proving it was
there.

Renewal is itself fenced, for the reason that matters most here: a stale worker that could
renew would keep alive precisely the Attempt recovery is trying to reclaim, which is the stuck
state this exists to end.

### A reclaimed Attempt is CANCELLED, and says who went quiet

Not `FAILED` — the work did not fail. Not `TIMED_OUT` — it did not exceed its own deadline.
Its *worker* stopped proving it was alive, and `CANCELLED` records that without inventing an
outcome the Attempt never had. `reclaimed_attempt_error` names the holder, so a reclaimed
Attempt is distinguishable from one a user cancelled — the distinction ADR-082426-f170 exists
to keep. From there the NodeRun parks for retry through that ADR's `RECOVERED` cause, which is
already the right shape and needed no new path.

### No TTL means no reclamation, ever

An Attempt with no lease, or a lease with no `expires_at`, is never expired. This is what keeps
the change additive: every existing caller keeps exactly today's behaviour, and nothing already
in flight becomes reclaimable because this shipped.

### No dedicated index, and why that is not an oversight

The obvious expression index on the cast expiry is impossible — `text::timestamptz` depends on
the session `TimeZone`, and PostgreSQL refuses to index a non-IMMUTABLE expression. It is also
unnecessary. `ix_canonical_attempts_one_active` (migration 012) is unique and partial on the
same `status IN ('created','running')` predicate, so at most one Attempt per NodeRun is ever a
candidate and the candidate set is bounded by **worker concurrency rather than by history**. A
sweep reads the Attempts running now, not every Attempt ever run.

## Acceptance Criteria

Each rule is asserted from one shared helper by a `spine`-parameterized test (all three stores,
in CI's postgres legs) and a `memory_spine` test (the criterion, where no database is
configured), for the reason recorded in `conftest.py`.

- [x] **AC-1**: A worker whose lease is still live is not reclaimed. The failure mode #232's
  acceptance names, and worse than the stuck state being fixed.
- [x] **AC-2**: Renewal extends the expiry and keeps the same fencing token.
- [x] **AC-3**: A lapsed lease is reclaimed as `CANCELLED`, naming the holder that stopped
  renewing.
- [x] **AC-4**: Reclamation is idempotent — two sweepers, or one restarted, is normal.
- [x] **AC-5**: An Attempt created without a TTL is never reclaimed.
- [x] **AC-6**: A stale fencing token cannot renew.

## Consequences

### Positive

- The crash boundary #143 named is closed on the task path, through the canonical seam rather
  than a second mechanism.
- The lease stops being half-built: `expires_at` now means something.

### Negative / Trade-offs

- A renewing worker writes periodically to `canonical_attempts` for the life of an Attempt.
  Bounded by concurrency and cadence, and the TTL/3 guidance is what keeps it modest.
- A caller that opts into a TTL and then forgets to renew will have healthy work reclaimed.
  That is the contract, and it is why the TTL is opt-in rather than defaulted.

### Neutral

- **`renew_lease` has no in-repo caller yet**, and the exact-debt ledger says so: it is banked
  under `core-public-api-surface` with four entries. It is the half of the contract a *worker*
  calls, and this repository's task runner does not heartbeat yet — wiring one is its own
  piece. Unlike the surfaces #225 and #244 name, its behaviour is exercised: six conformance
  tests across three stores, plus the fence refusal. `reclaim_expired_attempts` **is** wired,
  through `Container.recover_abandoned_attempts`.
- #232's sixth acceptance item — that the task runner and durable Graph executor no longer
  carry contradictory orphan semantics — is **not** closed by this. The two rules answer
  different questions and both are correct in their own scope, as recorded above. Making them
  one mechanism needs the Graph on the canonical store, which is #44.
