---
id: ADR-082526-7f02
title: "Dispatch identity belongs to the Attempt, not to the Run's admission provenance"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
substrate:
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-082326-c126
  - maistro-engine#ADR-082426-6201
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_chat_execution.py
ac-modules:
  AC-1: maistro.runs.chat_execution
  AC-2: maistro.runs.chat_admission
  AC-3: maistro.runs.chat_execution
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-7f02: Dispatch identity belongs to the Attempt, not to the Run's admission provenance

## Context

#223 asked for a chat turn to execute as a NodeRun and an Attempt, and stated one criterion
about where the dispatched agent is recorded:

> The NodeRun names the agent that actually handled the turn, and the Run's `agent_selection`
> no longer says `deferred` once one has.

PR #224 implemented the execution seam and **did not** implement that criterion. It recorded
the agent on the Attempt, left `agent_selection: "deferred"` in place permanently, and said so
in a docstring and in a test name. The strict PR→issue audit reopened #223 for exactly this,
and the objection was correct as process:

> That may be the better model, but the issue acceptance was never amended to that model, so
> the issue is not complete as written. Either implement the stated Run/NodeRun behavior or
> revise the issue/decision trail to make Attempt-owned dispatch identity the accepted
> contract and prove that contract.

This ADR is that revision. The argument for the shipped model existed only as a code comment,
which is not a decision trail — a reader could not tell a deliberate design from an oversight,
and the audit rightly refused to.

## Decision

**`agent_selection` is admission provenance and is never rewritten. The agent that ran is
recorded on the Attempt.**

Three reasons, in the order they matter.

**1. The marker's claim stays true.** `agent_selection: "deferred"` means *no agent was
resolvable at admission time*. That is a statement about a moment which has already passed,
and no later event can falsify it. Overwriting it once an agent runs would not correct a stale
value; it would replace a true statement about admission with a true statement about
execution, in a field whose name says admission.

**2. A record should not disagree with itself.** The Run's provenance is written once, at
admission, and read as history. Mutating it after the fact means two readers of the same Run
at different times see different accounts of the same instant, with nothing recording that it
changed. The audit trail is the product here (ADR-082326-c126); a mutable audit field is worth
less than an immutable one that says less.

**3. The question a reader has is "which agent ran", and the Attempt answers it.** The Attempt
is the record of the thing that executed, it already carries `executor_id` and timing, and
`ATTEMPT_AGENT_KEY` puts the agent beside them. Putting the same fact on the Run as well would
create two copies that can disagree once retries exist — and retries are the normal case, so
they would.

### What this does not say

It does not say the NodeRun should never carry dispatch identity. It says the *Run's admission
provenance* must not be retro-written. If a future need arises for per-node dispatch identity
— a multi-node Graph where each node runs a different agent — that belongs on the NodeRun as
its own field, written once when the node runs, not by mutating a Run field about admission.

`ADR-082426-6201` made the neighbouring call for in-agent delegation: the delegation chain
rides on the answer rather than inventing execution identity. Same instinct, one level up.

## Acceptance Criteria

- [x] **AC-1**: The Attempt records the agent that handled the turn, under a key the Conduit
  and the recorder spell identically.
- [x] **AC-2**: `agent_selection` remains `deferred` after a turn completes. Asserted directly,
  because this is the criterion #223 originally required the opposite of, and a silent
  regression here would look like the issue being "fixed".
- [x] **AC-3**: A turn whose Conduit reports no agent, or reports a non-string, records no
  agent key at all rather than a placeholder — an absent fact stays absent.

## Consequences

### Positive

- #223's acceptance now matches what the code does and why, so the audit that reopened it can
  close it against a stated contract rather than a code comment.
- The Run's provenance becomes immutable in fact and not merely by convention.

### Negative / Trade-offs

- Answering "which agent handled this Run" requires reading its Attempts rather than one field
  on the Run. For a one-node chat Run that is one extra hop, and `GET /v1/runs/{run_id}/node-runs`
  already exposes the path.
- Anyone reading only the Run sees `deferred` and may read it as "unknown" rather than "not
  known *yet, at admission*". The field name carries that, and this ADR is the place a reader
  is sent.

### Neutral

- Nothing changes in behaviour. This records a decision already implemented and tested; the
  diff is the decision trail, plus the acceptance criteria that make it checkable.
