---
id: SPEC-083026-ba26
title: Episodic memory survives a restart, and its scope rule is written once
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
  - maistro-engine#ADR-083026-a322
implements:
  - maistro-engine#ADR-083026-a322
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_episodic_store_conformance.py
  - packages/maistro-core/tests/memory/test_scope_predicate.py
source:
  - packages/maistro-core/src/maistro/persistence/pg_episodic.py
  - packages/maistro-core/src/maistro/persistence/sqlite_episodic.py
  - packages/maistro-core/src/maistro/memory/scopes.py
  - packages/maistro-core/src/maistro/memory/episodic/store.py
  - packages/maistro-core/src/maistro/container.py
ac-modules:
  AC-1: maistro.persistence.pg_episodic
  AC-2: maistro.persistence.pg_episodic
  AC-3: maistro.memory.scopes
  AC-4: maistro.persistence.pg_episodic
  AC-5: maistro.persistence.sqlite_episodic
  AC-6: maistro.persistence.sqlite_episodic
  AC-7: maistro.container
  AC-8: maistro.memory.episodic.store
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-ba26: Episodic memory survives a restart, and its scope rule is written once

## Context

`episodic_memories` was created by migration 001 and maintained by 006 and 008.
No Python outside `alembic/` names it. The only `EpisodicStore` was
`InMemoryEpisodicStore`, and `create_container` wired it whatever the
`database_url` said — so every tier, weight, reinforcement count and
contradiction count in ADR-080 lived in one process's heap.

ADR-083026-a322 records the decisions. This spec states what has to be true.

## Decision

Two durable stores — `PgEpisodicStore` and `SqliteEpisodicStore` — implement
`EpisodicStore` and `DecayableEpisodicStore`. `_wire_episodic_store` selects one
from the configured backend. Migration 026 adds the four record fields the table
never had.

Three rules carry the weight.

**The scope rule is written once.** `matches_scope` decides visibility in
Python, including the two clauses that stop cross-org leakage — a `global`
memory carrying an `org_id` is visible only to that org, and a `team` match also
requires the caller's org. `scope_predicate` in the same module returns the SQL
form of that rule, so the durable stores filter in the database without a second
copy of a security decision. A test drives both over the same corpus.

**Decay is one formula.** `apply_decay` reads the live rows, applies
`tick_decay` — the function the in-memory store applies — and writes each back.
It is not a SQL `UPDATE` restating the arithmetic, because `tick_decay` reads
each row's own `decay_rate` and `last_accessed_at` and a restatement would drift
from it silently.

**Retrieval bounds by weight, and says so.** `retrieve` takes the scope-matching
live rows ordered by weight down to `RETRIEVAL_CANDIDATE_CAP`, then ranks them
with the same `rank` the in-memory store uses. Below the cap all three stores
return the same answer; above it the durable ones consider the most heavily
weighted candidates, which is the ladder's own judgement of what matters.

## Retention and scope

An episodic memory is retained until it is deleted. Decay lowers weight; it
never removes a row, and the tier floors mean wisdom and regret cannot decay
below their bound at all — that is ADR-080's promise, and making it a database
property rather than a process property is what this change is for.

Scope is the soft axis set of root CLAUDE.md decision 7 / ADR-068: `global →
org → team → user → agent`. No hard tenancy boundary is introduced; `org_id`
here is a scope column, and the cross-org clauses in `matches_scope` are
visibility rules, not a tenancy guarantee.

## Consequences

### Positive
- Memory survives restarts and is shared between replicas.
- The visibility rule has one home.

### Negative / Trade-offs
- A decay sweep is a read and a write per live row.
- `retrieve` above the candidate cap can differ from the in-memory store.

### Neutral
- `memory://` deployments are unchanged.

## Acceptance Criteria

```gherkin
Feature: Episodic memory survives a restart, and its scope rule is written once

  @AC-1
  Scenario: A memory outlives the process that stored it
    Given a memory stored through a durable episodic store
    When a second store is built on the same database
    Then the memory is readable with its tier, weight and counts intact
    And a reinforcement recorded by the first store is visible to the second

  @AC-2
  Scenario: The row holds every field of the record
    Given a memory carrying a project, a decay rate, a shared marker and a review flag
    When it is stored and read back
    Then all four survive the round trip
    And a memory stored with none of them reads back as the record's defaults

  @AC-3
  Scenario: The scope rule means the same thing in both languages
    Given a corpus of memories across every scope and two organisations
    When the Python rule and the SQL predicate are each asked which are visible
    Then they select the same memories
    And a global memory belonging to another organisation is refused by both
    And a team memory whose organisation does not match the caller is refused by both

  @AC-4
  Scenario: Scope filtering happens in the database
    Given a durable store on a real PostgreSQL server
    When a scoped read is planned
    Then the plan applies the scope predicate rather than returning every row
    And a memory outside the scope is never fetched

  @AC-5
  Scenario: The decay ladder survives a restart
    Given memories at several tiers in a durable store
    When a decay sweep runs after time has passed
    Then the sweep reports what it scanned, what it decayed and what sat on its floor
    And a wisdom memory does not fall below its tier floor
    And the decayed weights are still there when a new store reads them

  @AC-6
  Scenario: The three stores agree
    Given the same memories in the in-memory, SQLite and PostgreSQL stores
    When each is asked to retrieve, list by scope and reinforce
    Then all three return the same memories in the same order

  @AC-7
  Scenario: The backend chooses the store
    Given a container configured with a PostgreSQL URL
    When it is built
    Then its episodic store is the PostgreSQL one
    And a SQLite URL selects the SQLite store
    And a memory:// URL still selects the in-memory store

  @AC-8
  Scenario: No document claims a durability that is not there
    Given the episodic memory sources and the migrations
    When they are read for what they claim about persistence
    Then the in-memory store states that its contents are process-local
    And no migration asserts that maistro.memory reads and writes a table it does not
```
