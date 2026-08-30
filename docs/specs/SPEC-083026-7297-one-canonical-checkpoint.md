---
id: SPEC-083026-7297
title: "One canonical checkpoint, and an unreached contract that says it is unreached"
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
  - maistro-engine#ADR-083026-ebcb
implements:
  - maistro-engine#ADR-083026-ebcb
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/events/test_checkpoint_contract_states_its_reach.py
source:
  - packages/maistro-core/src/maistro/events/checkpoints.py
  - packages/maistro-core/src/maistro/events/__init__.py
  - packages/maistro-core/src/maistro/orchestrator/waves/ensemble.py
ac-modules:
  AC-1: maistro.events
  AC-2: maistro.events
  AC-3: maistro.events
  AC-4: maistro.orchestrator.waves.ensemble
  AC-5: maistro.events
  AC-6: maistro.container
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-7297: One canonical checkpoint, and an unreached contract that says it is unreached

## Context

ADR-083026-ebcb records the decision. This spec states what has to be true.

The load-bearing discovery is that **removing one re-export does most of the
work**. `maistro.events.__init__` publishes `Checkpoint`, `CheckpointRef`,
`CheckpointStore`, `InMemoryCheckpointStore`, `SqliteCheckpointStore` and
`checkpoint_created_event` — and nothing anywhere imports any of them from
`maistro.events`. The one direct importer is `tests/events/test_checkpoints.py`,
which imports the module itself. So the re-export publishes a public surface for
a contract with no consumer, and it is exactly what makes the reachability walker
count the module as reached: `_imports` treats an `ImportFrom` in a package
`__init__` as an edge like any other.

Dropping the re-export therefore does three things at once: it stops the false
"reachable" reading, it retires the `_CHECKPOINT_STORE_OPERATIONS` keep-alive
that existed only to reference the re-exported names, and it lets the module be
classified in the ledger where every other unwired module already is.

## Decision

The module keeps its semantics and gains a statement of its reach. It is not
deleted: the schema-versioning and content-hash ideas are what a later
consolidation would want, and 428 lines of specified contract is a larger call
than this change should make. What must stop is its reading as current.

## Consequences

### Positive
- The unreachable share the convergence matrix publishes counts one more module
  honestly.
- A suppressed vulture signal becomes a recorded ledger entry with an owner.

### Negative / Trade-offs
- **A criterion about a deliberately-unreachable module cannot reach the top
  rung.** AC-1, AC-3 and AC-5 constrain `maistro.events.checkpoints`, and the
  `reachable` rung requires an anchor the reachability graph can get to — which
  this change removes on purpose. They anchor to `maistro.events` instead: the
  package whose `__init__` stopped publishing the contract, which the graph does
  reach, and which the tests read. That is the honest anchor rather than a
  convenient one, but it is worth naming, because the ladder cannot express
  "proven, about something intentionally unwired" and this is the shape any
  future retirement will hit.
- The general hole stays open: any *other* module reachable only through a
  package `__init__` re-export is still counted reached. Closing that in the
  walker would reclassify an unknown number of modules at once, which is its own
  change with its own evidence; this spec fixes the instance and names the class.

### Neutral
- `TaskCheckpoint` and the wave path are untouched.
- No migration: `canonical_checkpoints` never existed in PostgreSQL.

## Acceptance Criteria

```gherkin
Feature: One canonical checkpoint, and an unreached contract that says so

  @AC-1
  Scenario: The superseded contract states its reach and its successor
    Given the canonical checkpoint module
    When a reader looks for what constructs a Checkpoint in production
    Then the module says that nothing does
    And it names DurableRunRecord as the record that is the canonical checkpoint
    And it names the decision that supersedes it

  @AC-2
  Scenario: The package stops publishing a surface nothing consumes
    Given the events package
    When a reader lists what it exports
    Then the superseded checkpoint names are absent from it
    And no tuple of method references exists solely to keep them looking used

  @AC-3
  Scenario: A module reached only by a re-export is counted as unreached
    Given the reachability ledger
    When the canonical checkpoint module is classified
    Then it appears in the baseline as unreachable
    And the dispositions ledger gives it an owner and a rationale

  @AC-4
  Scenario: The two checkpoint stores do not collide by name
    Given both CheckpointStore protocols
    When a reader resolves which one a name denotes
    Then each is distinguishable without reading the import line
    And a test records which package exports which

  @AC-5
  Scenario: The absences the module claims are true
    Given the module's statement that its table has no migration
    When the revisions are scanned
    Then nothing creates the canonical checkpoint table
    And no module under any package source tree constructs the store

  @AC-6
  Scenario: A retired duplicate cannot become authoritative
    Given the container
    When it wires the stores an execution recovers from
    Then it wires no checkpoint store other than the durable-run path
    And the test fails if a second lifecycle store is wired
```
