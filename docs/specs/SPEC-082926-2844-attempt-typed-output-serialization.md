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
source:
  - packages/maistro-core/src/maistro/graph/nodes/base.py
ac-modules:
  AC-1: maistro.graph.nodes.base
  AC-2: maistro.graph.durable_runs.stores
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

`NodeResult.output` is
`dict[str, Any] | JsonValue | SerializeAsAny[BaseModel] | None`.

`SerializeAsAny` makes Pydantic serialize the *runtime* model's own fields
rather than the declared union member's empty schema. The fix is in the type,
so it holds wherever a `NodeResult` is serialized — every store, every
envelope, every caller. No call site pre-dumps, and none has to remember to.

Each of the three write branches is load-bearing, and the order is too:

- **`dict[str, Any]` first**, so a mapping never reaches the branches after it.
  A caller may pass values Pydantic can serialize that are not already JSON —
  `{"created_at": datetime.now(UTC)}` — and the other two branches would reject
  or mangle it.
- **`JsonValue`** for the shapes a serialized model actually takes on the way
  back in. The write side accepts *every* `BaseModel`, and a `RootModel`
  serializes to its root: a list, or a bare scalar. A dict-only read branch
  serialized those correctly and then raised on validation, which is worse than
  the loss this spec fixes — the old contract dropped them silently.
- **`SerializeAsAny[BaseModel]`** for the model itself, on the way out.

**A read-back is a JSON value, not the original class**, and not necessarily a
mapping: an object-rooted model returns a mapping, a list-rooted one a list, a
scalar-rooted one a scalar. The envelope never recorded which model produced
it, so reviving a class here would be a guess; the record returns the shape it
stored.

A downstream implementation of this contract must accept all three shapes on
read. Rejecting a non-mapping would reject records this implementation
considers valid.

## What was already emptied

Not repaired here, and deliberately so.

The first version of this spec shipped a repair function and a `maistro repair`
command over `SqliteDurableRunStore`. Both were aimed at the wrong store.
`container.py` wires `CanonicalDurableRunStore`, whose `get` assembles Attempts
from the canonical `RunStore`; nothing in production writes the document-shaped
`durable_graph_runs` table those commands opened. An operator running the survey
against a real deployment would have created an empty table and been told there
was nothing to repair — a false clean bill of health, which is worse than no
command, because this one answers.

The affected rows live in the canonical `RunStore`, and reaching them is a
different design: `DurableRunStore.update` mirrors lifecycle rather than
rewriting an Attempt's recorded result, so a repair has to go through the
canonical store's own write path. That is #637, not a patch to this change.

**So the disposition is documentation, not recovery.** An Attempt written under
the old contract holds `output: {}` where its node produced a typed value. For
the one Attempt its NodeRun accepted, the same output survives on
`NodeRun.result`, which the executor always dumped explicitly — so the record is
recoverable in principle, by a reader that knows where to look. For a superseded
retry, a failure, or an in-flight try there is no second copy anywhere, and
nothing distinguishes an emptied output from one that was genuinely `{}`.

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
  Scenario: A root-shaped output survives as its own shape
    Given a node result whose output is a model rooted in a list or a scalar
    When the result is serialized and revalidated
    Then the output is that list or scalar, not a mapping

  @AC-1
  Scenario: A mapping Pydantic serializes is still accepted
    Given a node result whose output maps a key to a value that is not JSON
    When the result is constructed and serialized
    Then it is accepted and the value serializes to its JSON form

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

```
