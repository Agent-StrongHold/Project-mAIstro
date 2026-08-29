---
id: SPEC-082926-87bb
title: Conductor State Durability Mode
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
  - maistro-engine#ADR-082926-87bb
implements:
  - maistro-engine#ADR-082926-87bb
related:
  - maistro-engine#SPEC-010
  - maistro-engine#SPEC-082926-0b72
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_state_durability_mode.py
source:
  - packages/hive-conductor/backend/services/durability.py
ac-modules:
  AC-1: '@flat/hive-conductor/services.durability'
  AC-2: '@flat/hive-conductor/services.durability'
  AC-3: '@flat/hive-conductor/routes.health'
  AC-4: '@flat/hive-conductor/services.durability'
  AC-5: '@flat/hive-conductor/services.durability'
  AC-6: '@flat/hive-conductor/services.model_store'
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-87bb: Conductor State Durability Mode

- **Status:** Active
- **Decision:** ADR-082926-87bb
- **Closes:** #333

## Scope

`Foundation._init_state`, the store wiring it performs, the health and readiness
surfaces that describe the result, and the write refusal that follows from it.

Out of scope: what the state database itself stores, which is SPEC-010; the
settings record specifically, which is SPEC-082926-0b72; and the data directory
the file lives in, which is #331.

## The mode

`CONDUCTOR_DURABILITY` takes exactly two values.

| value | means | on a state failure |
|---|---|---|
| `durable` (default) | this deployment requires state that outlives the process | degraded: readiness false, writes refused, error recorded |
| `ephemeral` | this deployment does not | in-memory stores, labelled, readiness true |

Any other value refuses startup. A mode is a declaration, and an unreadable
declaration is not a default.

## The recorded status

The Foundation records one `StateStatus` naming the requested mode, the backend
actually in use, whether that backend is durable, the initialization error if
there was one, and whether writes are refused. Every surface that describes
state durability reads that one record, so `/health`, `/health/ready` and the
settings record cannot disagree about it.

## Acceptance Criteria

```gherkin
Feature: Conductor state durability mode

  @AC-1
  Scenario: A durable deployment that cannot open its state is not ready
    Given CONDUCTOR_DURABILITY is durable
    And the state database cannot be opened
    When the Conductor starts
    Then readiness reports not ready
    And the recorded status names the initialization error

  @AC-1
  Scenario: A durable deployment that opens its state is ready
    Given CONDUCTOR_DURABILITY is durable
    And the state database opens
    When the Conductor starts
    Then readiness reports ready
    And the recorded status names a durable backend

  @AC-2
  Scenario: Ephemeral mode is entered by declaration
    Given CONDUCTOR_DURABILITY is ephemeral
    When the Conductor starts
    Then the stores are in-memory
    And the recorded status says the mode was requested, not inferred
    And readiness reports ready

  @AC-2
  Scenario: An unexpected exception cannot produce ephemeral mode
    Given CONDUCTOR_DURABILITY is durable
    And state initialization raises
    When the Conductor starts
    Then the recorded status still says durable was requested
    And it is not reported as an ephemeral deployment

  @AC-2
  Scenario: An unrecognised mode refuses startup
    Given CONDUCTOR_DURABILITY is neither durable nor ephemeral
    When the mode is read
    Then it is refused
    And no default is substituted

  @AC-3
  Scenario: Health reports the backend, its durability and the error
    Given a durable deployment whose state failed to initialise
    When /health is read
    Then it names the requested mode, the backend, durable false, and the error
    And /health/ready reports not ready

  @AC-4
  Scenario: A partial initialisation is degraded, not partly authoritative
    Given state initialisation fails after some stores have loaded
    When the Conductor starts
    Then every store is marked degraded
    And no store is left accepting writes as an authority

  @AC-5
  Scenario: A degraded process accumulates nothing to flush over durable rows
    Given a durable deployment whose state failed to initialise
    When a write is attempted
    Then it is refused
    And nothing is held that a later recovery could write over the durable rows

  @AC-6
  Scenario: A store promised durability refuses writes when it has none
    Given a store marked degraded
    When an item is assigned or removed
    Then StoreUnavailableError is raised
    And a read of already-loaded data still answers
```
