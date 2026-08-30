---
id: SPEC-083026-58de
title: The thumbs signal is durable, and is read through the store protocol
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
  - maistro-engine#ADR-083026-0596
implements:
  - maistro-engine#ADR-083026-0596
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_thumbs_conformance.py
  - packages/hive-conductor/backend/tests/test_thumbs_read_through_the_protocol.py
source:
  - packages/maistro-core/src/maistro/memory/outcomes.py
  - packages/maistro-core/src/maistro/persistence/pg_outcomes.py
  - packages/maistro-core/src/maistro/persistence/sqlite_outcomes.py
  - packages/maistro-core/src/maistro/protocols/memory.py
ac-modules:
  AC-1: maistro.memory.outcomes
  AC-2: maistro.memory.outcomes
  AC-3: maistro.persistence.sqlite_outcomes
  AC-4: '@flat/hive-conductor/services.optimizer'
  AC-5: maistro.persistence.pg_outcomes
  AC-6: '@flat/hive-conductor/services.engine'
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-58de: The thumbs signal is durable, and is read through the store protocol

## Context

`POST /v1/dag-runs/{run_id}/feedback` records a user's thumb as a
`maistro.memory.types.Outcome`. It writes through a protocol call — and the
store it writes to is a Hive-local `InMemoryOutcomeStore`, a list capped at
`MAX_OUTCOMES` with the oldest evicted. Every thumb is lost on restart.

`set_outcome_store` exists to bind the Container's durable store instead, and
had no production caller. All nine were tests, one of them named
`test_set_outcome_store_swaps_the_module_singleton` with a docstring saying
"the bridge / tests can hot-swap the store" — describing a bridge that did not
exist.

Making that call would have broken the optimizer. Both readers of the thumbs
signal walked `getattr(store, "_outcomes", [])`, the in-memory store's backing
list; the durable stores have no such attribute, so the expression yields `[]`
and the signal goes quietly empty. ADR-083026-0596 records the decision this
forces.

Three further defects surfaced when the behaviour was written down as a
conformance suite across all three stores, each of which made a claim in this
spec untestable until fixed:

- The SQLite `outcomes` table had no `thumb`, `thumb_comment`, `dag_id`,
  `dag_run_id`, `node_id`, `org_id`, `project_id` or `eval_judge_score` column.
  PostgreSQL gained them in migrations 006 and 010; the twin gained neither, so
  `record()` accepted a thumb, returned an id for it, and stored a row with the
  feedback removed.
- Its `list_outcomes` row mapping stopped at `created_at` — the same omission
  `PgOutcomeStore._row_to_outcome` was extracted to fix, still present here.
- `PgOutcomeStore.record` never wrote `created_at`, so that store alone let the
  column default decide when an outcome happened while the other two honoured
  the caller. Every time-windowed read answered a different question there than
  here.

## Decision

The thumbs signal is a protocol query, `OutcomeStore.list_thumbs`, answered
identically by all three stores; the Conductor binds the Container's durable
store at boot; and the aggregation both readers need lives in one place.

Two rules the query carries, which an implementation could not have inferred:

**A thumb with an empty `dag_id` belongs to every DAG.** Those were recorded
before the attribution wire existed. The old reader kept them deliberately, and
so does every implementation now — excluding them would discard feedback a user
actually gave in order to tidy a filter.

**Retention is stated.** `THUMB_WINDOW_DAYS` (90) and `THUMB_LIMIT` (5000) are
named constants with their reasoning written down. The reader they replace had
neither: its effective retention was whatever `MAX_OUTCOMES` happened to be and
its window was "since this process started". 90 days because a thumb judges a
node's behaviour and a rewritten node should not still be scored on last
quarter's feedback — but the optimizer's metrics window is 24 hours, so a short
thumbs window would make user feedback the one signal that vanished between
runs.

## Consequences

### Positive
- A thumb survives a restart, which the feedback endpoint always implied.
- One aggregation, so the optimizer and the topology comparison cannot disagree.
- A SQLite deployment can hold feedback at all.
- Every time-windowed read means the same thing on every backend.

### Negative / Trade-offs
- `run_optimizer`, `compare_variants` and their routes became async. Honest —
  they read a database — but a wider diff than binding the store alone.

### Neutral
- Without the bridge the Hive-local in-memory default stands, so a thumb still
  records deterministically in dev and test. It is not durable, and nothing says
  it is.

## Acceptance Criteria

```gherkin
Feature: The thumbs signal is durable, and is read through the store protocol

  @AC-1
  Scenario: A thumb recorded through the store comes back from it
    Given an outcome carrying a thumb and a comment
    When the thumbs are listed from any of the three stores
    Then that thumb and its comment are returned
    And an outcome carrying no thumb is not

  @AC-2
  Scenario: The DAG scoping rule is the same everywhere
    Given a thumb for another DAG, and one carrying no dag_id at all
    When the thumbs for one DAG are listed
    Then the other DAG's thumb is excluded
    And the unattributed one is included, on every store

  @AC-3
  Scenario: A SQLite deployment can hold a thumb
    Given a SQLite outcomes table created before the feedback columns existed
    When the schema is ensured and a thumb is recorded
    Then the thumb is readable, with every attribution field it was given
    And the rows the table already held are still there

  @AC-4
  Scenario: No production reader reaches into the store
    Given every production module in the Conductor and the core library
    When they are parsed for access to the store's private outcome list
    Then only the store that defines it touches it

  @AC-5
  Scenario: Retention and scope are the query's, not the process's
    Given thumbs inside and outside the retention window, and in another org
    When the thumbs are listed
    Then the ones outside the window are absent and the ones inside are present
    And another org's thumb is not returned
    And a bound read keeps the most recent

  @AC-6
  Scenario: The Conductor binds the container's durable store
    Given an engine started with a bridge to the core container
    When the outcome store is wired
    Then feedback writes go to the container's store
    And without a bridge the Hive-local store is left in place
```
