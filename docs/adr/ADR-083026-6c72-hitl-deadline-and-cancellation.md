---
id: ADR-083026-6c72
title: "A durable HITL deadline is an absolute boundary, and one canonical write settles it"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-082826-d9f5
implements: []
related:
  - maistro-engine#ADR-082826-08f0
  - maistro-engine#ADR-082826-b601
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_hitl_settlement.py
  - packages/hive-conductor/backend/tests/test_hitl_timeout_cancel.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-6c72: A durable HITL deadline is an absolute boundary, and one canonical write settles it

## Context

Every human node already accepts `timeout_seconds` and persists an absolute
`resume_at` when it pauses. Nothing consumes that deadline. A Run therefore
stays `PAUSED` forever unless a person answers, including after a restart and
long after the node said it should time out.

Cancellation is similarly incomplete. Cancelling an asyncio task while the
graph is actively walking terminalizes a Run, but a Run already parked on
human input has no canonical cancel operation. Product code could only invent
a synthetic answer or maintain a second status beside the Run, and either one
would make the product rather than the execution spine authoritative.

The answer, timeout, and cancel paths can race. A rule such as "the sweeper
usually runs first" is not a rule: process scheduling and restart timing would
decide the outcome. The durable record must make the winner deterministic.

## Decision

### The persisted deadline is the deadline

The `resume_at` inside the paused node's durable pause entry is an absolute UTC
deadline. A restart never recomputes it from `timeout_seconds`, so process
uptime cannot extend a human decision window.

An answer is valid only while its pause deadline is still in the future. Once
the deadline has elapsed, an answer is refused even if the timeout sweep has
not run yet. This makes timeout a property of the durable record rather than
of sweep cadence.

### The canonical store serializes all three decisions

Answer, timeout, and cancel are mutations on `DurableRunStore`. Each backend
performs validation and persistence inside its existing serialization
boundary; the SQLite document twin uses one `BEGIN IMMEDIATE` transaction so
two store instances cannot both read `PAUSED` and commit different outcomes.

Before the deadline, the first valid serialized write wins. At or after the
deadline, timeout wins by rule: an answer cannot outrun an already elapsed
deadline merely because the bounded sweep has not observed it yet. A later
answer, timeout, or cancel sees terminal or queued state and is refused without
rewriting evidence.

### Timeout and cancel are logical outcomes, not answers

Timeout terminalizes the triggering human `NodeRun` as `TIMED_OUT` and the
parent `Run` as `TIMED_OUT`. Cancel terminalizes both as `CANCELLED`. Other
open frontier members are cancelled by the existing parent-terminalization
rule because those nodes did not themselves time out.

Neither transition writes `hitl_answers`. Instead, immutable-by-history
settlement evidence is retained under `GraphExecutionState.metadata` with the
outcome, deciding node, decision time, and original pause entry. That lets a
reopened store distinguish waiting, answered, timed out, and cancelled work.

The already yielded physical `Attempt` remains the evidence of the pause. No
new Attempt is created just to overwrite it with a logical terminal outcome.

### Expiry is a bounded tick; products only request transitions

`expire_hitl_pauses` is bounded, idempotent, operator-scheduled, and never
self-starting, matching the repository's other ticks. It finds paused records,
selects elapsed human pauses from durable evidence, and asks the store to
timeout each one. The store revalidates the deadline under the write boundary,
so discovery is not authority.

The Conductor exposes the tick and cancel request through its existing HITL
router. Those routes do not edit lifecycle fields. They call the canonical
store and translate its refusal into HTTP.

## Consequences

### Positive

- `timeout_seconds` has production meaning and restart cannot extend it.
- A late human response cannot revive or rewrite terminal work.
- Timeout and cancellation are visible on canonical Run and NodeRun records.
- Races have one winner under a stated rule rather than scheduler luck.
- No product-local lifecycle or synthetic timeout answer is introduced.

### Negative / Trade-offs

- Timing out one member of a human frontier times out the Run and cancels its
  still-open siblings. Partial continuation after one required human decision
  expires would need an explicit Graph branch, not an implicit store policy.
- Products must schedule the bounded expiry tick. Importing the library does
  not start background work.

### Neutral

- A human node's existing yielded Attempt is preserved unchanged.
- The answer/resume path remains the way successful human input continues a
  graph; timeout and cancel deliberately do not resume it.
