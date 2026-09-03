---
id: SPEC-083026-73c1
title: Durable HITL timeout and cancellation
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-083026-6c72
implements:
  - maistro-engine#ADR-083026-6c72
related:
  - maistro-engine#SPEC-082926-a44e
  - maistro-engine#SPEC-081226-a66b
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_hitl_settlement.py
  - packages/hive-conductor/backend/tests/test_hitl_timeout_cancel.py
source:
  - packages/maistro-core/src/maistro/graph/durable_runs/hitl.py
  - packages/maistro-core/src/maistro/graph/durable_runs/stores.py
  - packages/maistro-core/src/maistro/graph/durable_runs/canonical_store.py
  - packages/hive-conductor/backend/routes/hitl.py
ac-modules:
  AC-1: maistro.graph.durable_runs.hitl
  AC-2: maistro.graph.durable_runs.stores
  AC-3: maistro.graph.durable_runs.stores
  AC-4: maistro.graph.durable_runs.stores
  AC-5: maistro.graph.durable_runs.stores
  AC-6: '@flat/hive-conductor/routes.hitl'
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-73c1: Durable HITL timeout and cancellation

## Contract

Human pauses carry an absolute deadline in their durable pause entry. The
canonical store is the only component allowed to accept an answer, time out a
pause, or cancel it. Timeout and cancel terminalize canonical execution state,
retain settlement evidence, and never masquerade as human input.

The deadline check belongs inside the same serialized mutation as the answer.
This prevents a late answer from winning only because the expiry tick was
delayed. For a valid answer before the deadline, whichever valid store write
commits first wins; every later contender is refused.

## Acceptance Criteria

```gherkin
Feature: Durable human decisions have real deadlines and cancellation

  @AC-1
  Scenario: A human pause times out after a restart
    Given a paused human NodeRun with a persisted absolute deadline
    And the durable store is closed and reopened
    When the expiry tick runs after that deadline
    Then the Run is TIMED_OUT
    And the human NodeRun is TIMED_OUT
    And durable evidence names the deadline and deciding node

  @AC-2
  Scenario: Cancellation survives restart
    Given a paused human NodeRun
    When the canonical store cancels it
    And the durable store is reopened
    Then the Run and human NodeRun remain CANCELLED
    And no human answer was fabricated

  @AC-3
  Scenario: A late answer cannot revive terminal work
    Given a paused human NodeRun whose durable deadline has elapsed
    When a human answer arrives before the expiry tick observes it
    Then the answer is refused
    And a subsequent expiry tick records TIMED_OUT
    And another answer cannot change the terminal evidence

  @AC-4
  Scenario: Racing decisions have one deterministic winner
    Given answer, timeout, and cancel contend for one paused node
    When their canonical store mutations run concurrently
    Then exactly one valid outcome is persisted
    And every losing mutation is refused

  @AC-5
  Scenario: Logical settlement does not rewrite physical history
    Given the human NodeRun paused through a yielded Attempt
    When it times out or is cancelled
    Then the yielded Attempt remains unchanged
    And no additional Attempt is created

  @AC-6
  Scenario: Product code requests rather than owns settlement
    Given a paused human NodeRun
    When the Conductor cancel endpoint or bounded expiry endpoint is called
    Then it delegates the transition to DurableRunStore
    And the product keeps no second lifecycle field
```

## Collision boundary

This contract is implemented only in HITL-specific durable Graph stores,
focused HITL tests, and the existing HITL router. It does not alter Container,
the admitted-Run consumer, checkpoint authority, Conductor durability mode,
Invocation/provenance, shared ratchets, or workflow files.
