---
id: SPEC-082926-a44e
title: A parked schedule Run resumes where it stopped, or stays parked
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
  - status: AC Defined
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-082826-b601
implements:
  - maistro-engine#ADR-082826-b601
related:
  - maistro-engine#SPEC-082926-d90e
  - maistro-engine#ADR-082426-6201
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_parked_run_resume.py
source:
  - packages/maistro-core/src/maistro/graph/nodes/base.py
  - packages/maistro-core/src/maistro/runs/consumption.py
  - packages/maistro-core/src/maistro/container.py
ac-modules:
  AC-1: maistro.runs.consumption
  AC-2: maistro.runs.consumption
  AC-3: maistro.runs.consumption
  AC-4: maistro.runs.consumption
  AC-5: maistro.runs.consumption
  AC-6: maistro.graph.nodes.base
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-a44e: A parked schedule Run resumes where it stopped, or stays parked

## Context

SPEC-082926-d90e gave the schedule consumer a real yield disposition: a node
that pauses records `AttemptStatus.YIELDED`, and the NodeRun parks `PAUSED` or
`WAITING` instead of being recorded as a failure. That is the write half.

There is no read half. `Container.execute_admitted_runs` polls `QUEUED` only,
so a Run that yielded is durably correct and **permanently inert** — no tick
will look at it again.

The obvious workaround is worse than the gap. Requeueing a parked Run to
`QUEUED` makes the next tick execute it *from scratch*: `ScheduleAttemptExecutor`
opens a new NodeRun at the node's beginning. For a HITL node that is merely
wasteful. For `agent.delegate_remote` it is not — the node dispatches the
delegation **before** it pauses, so a re-run dispatches a second one. A pause
meant to preserve work would duplicate it.

There is a third state, found while writing this. `jira.wait_for_subtasks`
reads its first-reach timestamp from `ctx.metadata["wait_first_seen:<node_id>"]`
— a key **nothing in the system has ever written**; only tests do. So on every
real path it takes the first-reach branch again, and the overall deadline it
records can never be reached. Latent while nothing resumed; an unbounded poll
the moment something does.

## Decision

### A pause states what wakes it

`PAUSE_RESUME_CONDITIONS` maps each `paused_reason` to one of two answers,
beside the `PAUSE_REASON_OWNERS` table that already states *who* is owed the
next action. The two questions are different and neither derives from the
other: `awaiting_remote_delegation` is owed by the system and is still
answer-gated, because the system that owes it is another agent session.

- `RESUME_ON_ELAPSED` — the node **polls**. Re-entering it re-reads the world,
  which is what it paused to do, and is idempotent by construction.
- `RESUME_ON_ANSWER` — the node **dispatched** something and waits to be told
  the outcome. Re-entering it without that answer takes the dispatch branch
  again.

A reason absent from the table is *unclassified*, not resumable. The pause
stays parked and visible, which is the honest answer for a condition nobody
has stated, and it makes adding a pausing node a question a reviewer sees.

### Only an elapsed poll is resumed, and only through its own NodeRun

`Container.resume_parked_runs` is the fourth tick beside its three siblings and
keeps their discipline: bounded, idempotent, operator-scheduled, never
self-starting (ADR-019). It resumes a Run only when all of the following hold:
the Run is parked and from an allowlisted admission source; it has exactly one
NodeRun; that NodeRun's latest Attempt is `YIELDED`; the pause reason is
`RESUME_ON_ELAPSED`; and `resume_at` has passed.

A `FAILED` Attempt also parks its NodeRun `WAITING`, and *that* park means a
retry decision is owed. Taking it by finding the row would be this tick
deciding something it does not own.

Resumption calls `retry_node`, not `execute_node`: a second NodeRun for the
same node would make the Run's own history claim the node was reached twice,
and the pause would have bought nothing.

The claim is the parked→RUNNING transition itself, exactly as the QUEUED→RUNNING
transition is the claim for `execute_admitted_runs`. The transition table is
the mutex.

### The pause carries its own state forward

The previous pause's metadata is copied verbatim into the resumed node's
context under one key, and `resumed_pause(ctx)` reads it back. Verbatim,
because the consumer must not learn what any node's pause *means*: it copies a
dict it does not read, and each node reads the keys it itself wrote.

`jira.wait_for_subtasks` now reads `first_seen` from there, with the old
`wait_first_seen:` key kept as a fallback. That is what makes its deadline
reachable, and therefore what makes the resume tick a bounded wait rather than
a loop.

### What this deliberately does not do

Answer-gated pauses are not resumed at all. Delivering "resumed once the answer
arrives" needs somewhere for an answer to a *canonical* Run to be written, and
there is nowhere: the HITL door (#244) writes to `DurableRunStore`, the document
store, which nothing on the canonical path reads. AC-2 therefore states the
property this change enforces — a timer never re-enters an answer-gated pause —
rather than implying a positive half that does not exist. AC-4 is true because
of it.

## Consequences

### Positive
- A parked schedule Run is no longer permanently inert.
- A resumed node continues under its own NodeRun, so the Run's history says
  once what happened once.
- A poll's deadline can be reached for the first time on any path.

### Negative / Trade-offs
- Only one pause reason is `RESUME_ON_ELAPSED` today, so the tick is narrow.
  That is the classification being honest rather than the mechanism being
  weak: the other six genuinely need an answer.
- Answer-gated Runs stay parked until a canonical answer surface exists. They
  were inert before too, so nothing regresses — but the gap is now named.

### Neutral
- No change to the yield write path, to the pause evidence's shape, or to how
  any node decides to pause.

## Acceptance Criteria

```gherkin
Feature: A parked schedule Run resumes where it stopped

  @AC-1
  Scenario: An elapsed poll is picked up and resumed
    Given a schedule Run parked on a pause whose resume time has passed
    When the resume tick runs
    Then the Run is resumed

  @AC-2
  Scenario: A timer never re-enters a pause that is waiting for an answer
    Given a Run parked on an answer-gated pause whose resume time has passed
    When the resume tick runs
    Then the Run is left parked

  @AC-3
  Scenario: Resuming continues the parked NodeRun
    Given a parked Run with one NodeRun and one yielded Attempt
    When it is resumed
    Then the Run still has one NodeRun
    And that NodeRun has a second Attempt

  @AC-4
  Scenario: A dispatched delegation is not dispatched again
    Given a Run parked after dispatching a remote delegation
    When the resume tick runs
    Then no second delegation is dispatched

  @AC-5
  Scenario: A pause with no stated resume condition stays parked
    Given a Run parked on a pause reason that names no resume condition
    When the resume tick runs
    Then the Run is left parked and visible

  @AC-6
  Scenario: A resumed poll can reach its own deadline
    Given a polling node that recorded a deadline when it first paused
    When it is resumed after that deadline
    Then it reports having timed out rather than pausing again
```
