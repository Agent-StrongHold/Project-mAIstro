---
id: SPEC-082926-2844
title: Attempt typed output serialization
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
  - maistro-engine#ADR-081226-a66b
implements:
  - maistro-engine#ADR-081226-a66b
related:
  - maistro-engine#ADR-081226-69ee
  - maistro-engine#ADR-062
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/graph/durable_runs/test_typed_attempt_output.py
  - packages/maistro-core/tests/graph/durable_runs/test_typed_output_recovery.py
source:
  - packages/maistro-core/src/maistro/graph/nodes/base.py
  - packages/maistro-core/src/maistro/graph/durable_runs/repair.py
ac-modules:
  AC-1: maistro.graph.nodes.base
  AC-2: maistro.graph.durable_runs.stores
  AC-3: maistro.graph.durable_runs.repair
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-2844: Attempt typed output serialization

- **Status:** Active
- **Decision:** ADR-081226-a66b
- **Closes:** #566

## Context

ADR-081226-a66b makes the Attempt the physical execution record: what actually
ran, and what it produced. `Attempt.result` holds the node's whole
`NodeResult`, and `NodeResult.output` was declared
`dict[str, Any] | BaseModel | None`.

Pydantic serializes a union member typed as bare `BaseModel` through that
declared schema, and that schema has no fields. So a node returning a typed
model persisted as `output: {}`. Nothing caught it, because the graph still
produced the right answer: the executor dumps the model explicitly with
`model_dump(mode="json")` before writing `NodeRun.result`, so the *logical*
outcome survived and only the *physical* record was emptied. An Attempt in that
state cannot support replay, cannot be diffed against a retry, and describes
the same execution differently depending on whether it has been through a
store.

## Scope

`NodeResult.output`'s serialization, and the disposition of Attempts already
written with an emptied output.

Out of scope: which model a node declares as its `output_schema`, and the
executor's `_result_output` normalization onto `NodeRun.result`, which was
already correct and is unchanged.

## The contract

`NodeResult.output` is `dict[str, Any] | SerializeAsAny[BaseModel] | None`.
`SerializeAsAny` makes Pydantic serialize the *runtime* model's own fields
rather than the declared union member's empty schema.

The fix is in the type, so it holds wherever a `NodeResult` is serialized —
every store, every envelope, every caller. No call site pre-dumps, and none
has to remember to.

Reading a record back gives the output as a mapping, not as the original
class. The envelope never recorded which model produced it, so reviving a class
here would be a guess; the fields are what the record promised and the fields
are what it returns.

## Recovering what was already emptied

`maistro.graph.durable_runs.repair` restores an emptied Attempt output from
evidence the same record already holds, and reports what it cannot.

Recoverable is exactly one case: the Attempt the NodeRun accepted.
`AcceptedNodeOutcome.attempt_result.attempt_id` names it by id, and
`NodeRun.result` holds the same output correctly dumped. That is an exact key,
not a heuristic.

Everything else is unrecoverable and is left untouched. A superseded retry, a
failure, or an in-flight try has no second copy anywhere — its output was
written once, into the field this defect emptied — and nothing in the record
tells an emptied output apart from an output that was genuinely `{}`.
Inventing a value for a physical execution record is worse than an honest gap.

Recovery does not run on its own. Rewriting stored execution history is an
operator's decision, so it is a function an operator or a migration calls, and
it returns what it changed.

## Acceptance Criteria

```gherkin
Feature: Attempt typed output serialization

  @AC-1
  Scenario: A typed output serializes its own fields
    Given a node result whose output is a typed model
    When the result is serialized to JSON
    Then the model's own fields are in the output

  @AC-1
  Scenario: A typed output survives a round trip
    Given a node result whose output is a typed model
    When the result is serialized and revalidated
    Then the output holds the same fields it was given

  @AC-1
  Scenario: A mapping output is unchanged
    Given a node result whose output is a plain mapping
    When the result is serialized and revalidated
    Then the output is the same mapping

  @AC-1
  Scenario: An absent output is unchanged
    Given a node result with no output
    When the result is serialized and revalidated
    Then the output is still absent

  @AC-2
  Scenario: The in-memory store keeps a typed Attempt output
    Given a durable run record whose Attempt result carries a typed output
    When it is written to the in-memory durable run store and read back
    Then the Attempt's persisted output holds the fields the node produced

  @AC-2
  Scenario: The SQLite store keeps a typed Attempt output
    Given a durable run record whose Attempt result carries a typed output
    When it is written to the SQLite durable run store and read back
    Then the Attempt's persisted output holds the fields the node produced

  @AC-3
  Scenario: The accepted Attempt is restored from the record's own evidence
    Given a record whose accepted Attempt was written with an emptied output
    And the NodeRun that accepted it recorded the output it produced
    When the record is passed to recovery
    Then the Attempt's output holds what the NodeRun recorded
    And the report names it as recovered

  @AC-3
  Scenario: Recovery changes nothing else in the Attempt result
    Given a record whose accepted Attempt was written with an emptied output
    When the record is passed to recovery
    Then every other field of the Attempt result is what it was

  @AC-3
  Scenario: A superseded Attempt is reported unrecoverable and left alone
    Given a NodeRun with an emptied superseded Attempt and an accepted one
    When the record is passed to recovery
    Then the superseded Attempt's output is still empty
    And the report names it unrecoverable because the NodeRun accepted another

  @AC-3
  Scenario: An Attempt no NodeRun accepted recovers nothing
    Given a record whose NodeRun accepted no Attempt
    When the record is passed to recovery
    Then the record is returned unchanged
    And the report names the emptied Attempt unrecoverable

  @AC-3
  Scenario: An accepted Attempt with no stored output is named separately
    Given a record whose NodeRun accepted an Attempt but recorded no output
    When the record is passed to recovery
    Then the report says there was no evidence to restore from

  @AC-3
  Scenario: An Attempt that genuinely produced a value is not touched
    Given a record whose Attempt already holds the output it produced
    When the record is passed to recovery
    Then the record is returned unchanged
    And the report names nothing

  @AC-3
  Scenario: An Attempt with no result at all is not an emptied output
    Given a record whose Attempt has no result
    When the record is passed to recovery
    Then the report names nothing

  @AC-3
  Scenario: A survey reports across records and changes nothing
    Given one recoverable record and one unrecoverable record
    When they are surveyed
    Then the report counts one of each
    And neither record is modified
```
