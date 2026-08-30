---
id: SPEC-083026-b2b5
title: "Learnings, outcomes and design outputs carry their producing execution"
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
  - maistro-engine#ADR-083026-1cb1
  - maistro-engine#ADR-019
implements:
  - maistro-engine#ADR-083026-e602
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_record_provenance.py
  - packages/maistro-design/tests/test_output_provenance.py
ac-modules:
  AC-1: maistro.observability.correlation
  AC-2: maistro.persistence.pg_learnings
  AC-3: maistro.persistence.pg_outcomes
  AC-4: maistro.persistence.sqlite_learnings
  AC-5: maistro.memory.learnings.store
  AC-6: maistro.persistence.pg_learnings
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-b2b5: Learnings, outcomes and design outputs carry their producing execution

## Context

ADR-083026-e602 records the decision. This spec states what has to be true for
it to count as done.

The starting state, verified against `develop` at `453c6f1`: `learnings` (`001:71`)
has no producer column; `outcomes` (`001:114`, extended by `010`) carries the
Conductor's `dag_run_id` and not the canonical spine; `design_outputs`
(`003:97`) has no producer column of any kind.

## Goals

- Migration 025 adds nullable `run_id`, `node_run_id` and `attempt_id` to
  `learnings`, `outcomes` and `design_outputs`, each with an index on `run_id`.
- `Learning`, `Outcome` and `DesignOutput` carry the three fields.
- `observed_provenance` in `maistro.observability.correlation` resolves a
  record's producer: caller first, ambient context second.
- Every store that persists one of the three fills provenance at write time and
  reads it back: `PgLearningStore`, `SqliteLearningStore`,
  `InMemoryLearningStore`, `PgOutcomeStore`, `SqliteOutcomeStore`,
  `PgDesignProjectStore`.
- `LearningStore.produced_by(run_id, *, org_id)` on the protocol and all four
  implementations.

## Non-goals

- `episodic_memories`. Nothing outside `alembic/` references it and its only
  store holds a dict; columns there would be a claim with nothing behind it
  (#710).
- Backfilling rows written before this. There is no source for an id that was
  never recorded.
- Closing the SQLite outcomes twin's other eight-column divergence from
  PostgreSQL, or its `str()`-not-JSON `tool_calls` write. Both are real, both
  predate this, and neither is this change's to fix.
- Sessions correlating to Runs, and backup/restore — #64's third and fifth
  bullets, each its own sub-issue.

## Acceptance Criteria

```gherkin
Feature: Learnings, outcomes and design outputs carry their producing execution

  @AC-1
  Scenario: The caller's answer beats the ambient one
    Given an execution context naming a Run and an Attempt
    When a producer is resolved with a Run the caller named
    Then the caller's Run is kept and the ambient Attempt fills the rest
    And a record resolved outside any execution names no producer at all

  @AC-2
  Scenario: A learning names the execution that taught it
    Given a learning stored inside a running Attempt by a caller that named nothing
    When the Run is asked what it produced
    Then the learning comes back naming that Run, NodeRun and Attempt
    And a learning stored outside any execution names none

  @AC-3
  Scenario: An outcome carries canonical identity beside the product's
    Given an outcome recorded inside an Attempt and carrying a DAG run id
    When the stored row is read
    Then it holds the canonical Run, NodeRun and Attempt
    And it still holds the DAG run id it was given

  @AC-4
  Scenario: A record produced outside an execution stores absence, not emptiness
    Given a record written with no execution in scope
    When its producer columns are read
    Then all three are null rather than empty strings

  @AC-5
  Scenario: Every backend answers the same way
    Given the same learning stored through in-memory, SQLite and PostgreSQL
    When each is asked what a Run produced
    Then all three name the producer identically
    And a blank Run returns nothing rather than every unattributed record

  @AC-6
  Scenario: A store file created before the columns keeps its rows
    Given a SQLite database holding learnings written before this change
    When the store ensures its schema
    Then the producer columns exist and the older learnings are still readable
    And a learning stored afterwards is found by the Run that produced it
```
