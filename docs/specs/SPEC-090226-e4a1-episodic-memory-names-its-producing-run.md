---
id: SPEC-090226-e4a1
title: "An episodic memory names the execution that stored it"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-09-02
accepted: 2026-09-02
history:
  - status: Proposed
    date: 2026-09-02
  - status: Accepted
    date: 2026-09-02
  - status: AC Defined
    date: 2026-09-02
substrate:
  - maistro-engine#ADR-083026-1cb1
  - maistro-engine#ADR-083026-a322
implements:
  - maistro-engine#ADR-090226-9c3f
related:
  - maistro-engine#SPEC-083026-b2b5
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_episodic_provenance.py
  - tests/migrations/test_episodic_provenance_migration.py
ac-modules:
  AC-1: maistro.memory.episodic.store
  AC-2: maistro.persistence.sqlite_episodic
  AC-3: maistro.persistence.pg_episodic
  AC-4: maistro.persistence.pg_episodic
  AC-5: maistro.persistence.sqlite_episodic
  AC-6: maistro.persistence.sqlite_episodic
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-090226-e4a1: An episodic memory names the execution that stored it

## Context

ADR-090226-9c3f records the decision. This spec states what has to be true for
it to count as done.

The starting state, against `develop` at `139e3be1`: `EpisodicMemory`
(`types/memory.py`) has no producer field; `episodic_memories` has none either;
no episodic store calls `observed_provenance`. #64's first acceptance bullet —
"memory writes/retrieval can identify producing evidence/Run where applicable"
— is met for learnings and outcomes (#709) and unstarted for episodic memory,
the record kind whose recall now builds the prompt (#622).

## Goals

- `EpisodicMemory` carries `run_id`, `node_run_id`, `attempt_id`.
- Every `EpisodicStore` implementation fills them at write time from
  `observed_provenance` and reads them back.
- Migration `031` adds the nullable columns and the `run_id` index; both
  stores' `ensure_schema` upgrades pre-`031` state in place.
- `EpisodicStore.produced_by(run_id, *, org_id="")` on the protocol and all
  three implementations.

## Non-goals

- Making `InMemoryEpisodicStore` upsert. One-row-per-id is the durable
  contract (ADR-083026-a322); the append is unchanged.
- Backfilling rows written before this. There is no source for an id that was
  never recorded.
- `memory_entries` (codebase knowledge, not execution output) and the
  Invocation axis of artifact provenance, which remains blocked on #55 exactly
  as #717 recorded.

## Acceptance Criteria

```gherkin
Feature: An episodic memory names the execution that stored it

  @AC-1
  Scenario: A memory stored inside an Attempt carries it
    Given an execution context naming a Run, a NodeRun and an Attempt
    When a memory is stored by a caller that named nothing
    Then the memory reads back naming that Run, NodeRun and Attempt
    And asking the Run what it remembered returns that memory

  @AC-2
  Scenario: A memory stored outside an execution names no producer
    Given no execution in scope
    When a memory is stored
    Then retrieval returns it with no producer
    And its durable row holds NULL in all three columns, not an empty id

  @AC-3
  Scenario: The caller's answer beats the ambient one
    Given an execution context naming a Run
    When a memory is stored with a different Run the caller named
    Then the caller's Run is kept and the ambient Attempt fills the rest

  @AC-4
  Scenario: The upsert moves the producer with the content
    Given a memory stored under one Run
    When the same memory_id is stored again under another Run
    Then the surviving row names the second Run
    And the first Run's produced_by returns nothing

  @AC-5
  Scenario: produced_by answers only within scope
    Given memories stored by one Run in two organisations
    When produced_by is asked for that Run in one organisation
    Then only that organisation's memories are returned
    And a blank run_id returns nothing rather than every unattributed memory
    And a deleted memory is not returned

  @AC-6
  Scenario: A store file created before the columns keeps its rows
    Given a SQLite database holding memories written before this change
    When the store ensures its schema
    Then the producer columns exist and the older memories are still readable
    And a memory stored afterwards is found by the Run that produced it
```

The PostgreSQL half of the same preservation property — migration `031`
landing nullable `run_id`/`node_run_id`/`attempt_id` with the `run_id` index,
and `downgrade 030` removing them again — is proven by
`tests/migrations/test_episodic_provenance_migration.py` rather than declared
as a criterion: a migration is a history file, not a module the reachability
graph knows, so an `ac-modules` anchor for it would claim the wrong code runs
it and the criterion could never honestly reach the `reachable` rung. Recorded
here, in the prose a reviewer reads, instead.
