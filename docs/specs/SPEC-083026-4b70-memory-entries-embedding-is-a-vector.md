---
id: SPEC-083026-4b70
title: "memory_entries.embedding holds vectors, and its type is asserted rather than assumed"
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
  - maistro-engine#ADR-082226-5104
  - maistro-engine#ADR-082326-8194
implements:
  - maistro-engine#ADR-083026-4b70
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/migrations/test_memory_entries_embedding_type.py
ac-modules:
  AC-1: maistro.memory.vectors
  AC-2: maistro.memory.vectors
  AC-3: maistro.memory.vectors
  AC-4: maistro.persistence.pg_learnings
  AC-5: maistro.memory.vectors
  AC-6: maistro.memory.store
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-4b70: memory_entries.embedding holds vectors, and its type is asserted rather than assumed

## Context

ADR-083026-4b70 records the decision. This spec states what has to be true for
it to count as done.

The starting state, verified against a migrated PostgreSQL 18 + pgvector
database at `develop` `fdb6bcb`:

```
learnings.embedding       => vector(1536)
memory_entries.embedding  => text
```

Migration `001` creates `memory_entries.embedding` as `sa.Text` and then guards
the vector `ALTER` with `IF NOT EXISTS`, so PostgreSQL skips it silently. Three
artefacts assert the type that is not there: the ORM model's `Vector(1536)`
mapping, `memory/vectors.py`'s claim that `001` created it, and `011`'s
downgrade note.

## Goals

- Migration `029` converts `memory_entries.embedding` to `vector(1536)` and adds
  `ix_memory_entries_embedding_hnsw` with `vector_cosine_ops`, matching `011`.
- Values that the target type cannot accept move to `embedding_unconvertible`
  rather than aborting the upgrade or being discarded.
- The tests read the column's real type from `pg_catalog` and fail on `text`.
- `001`'s comment and `vectors.py`'s migration reference stop contradicting the
  database.

## Non-goals

- Changing `EMBEDDING_DIMENSIONS`. ADR-082326-8194 decided 1536 and is Accepted;
  changing the width in the same revision that repairs the type would make it
  impossible to attribute a later failure to either.
- `outcomes` and `episodic_memories`. #188 requires the producer and the
  consumer to land together for a *new* column; this is a repair of a column
  that already exists and that the ORM already maps.
- Rewriting `001`. It has run everywhere; a migration records what happened.

## Acceptance Criteria

```gherkin
Feature: memory_entries.embedding holds vectors, and its type is asserted

  @AC-1
  Scenario: The column's real type is a vector, not a column that merely exists
    Given a database migrated to head
    When the type of memory_entries.embedding is read from the catalog
    Then it is vector at the declared width
    And a check that only asked whether the column exists would have passed before this

  @AC-2
  Scenario: A value the target type cannot accept is preserved, not lost
    Given a database at the broken revision holding malformed and wrong-width text
    When the repair runs
    Then the upgrade succeeds
    And each unconvertible value is readable under a name that says it could not be read

  @AC-3
  Scenario: A value the target type can accept survives unchanged
    Given a row holding a well-formed vector at the declared width
    When the repair runs
    Then that row still holds the same vector

  @AC-4
  Scenario: Similarity and scope resolve in one query
    Given rows in one workspace carrying vectors
    When the nearest are asked for within that workspace
    Then the ranking comes back
    And the scope predicate appears in the database's own plan rather than being applied after

  @AC-5
  Scenario: One index strategy, not two
    Given the repaired column
    When its index is read back
    Then it is HNSW over the cosine operator class
    And it is named the way migration 011 names the equivalent index on learnings

  @AC-6
  Scenario: Nothing left in the tree still describes the column wrongly
    Given the artefacts that name this column's type or its creating migration
    When each is read
    Then none of them claims 001 produced a vector column
    And none of them names a migration file that does not exist
```
