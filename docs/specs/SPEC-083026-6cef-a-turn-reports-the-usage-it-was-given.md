---
id: SPEC-083026-6cef
title: A turn reports the usage it was given, and the unreached layer says it is unreached
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
  - maistro-engine#ADR-083026-aba1
implements:
  - maistro-engine#ADR-083026-aba1
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/capabilities/test_invocation_layer_states_its_reach.py
  - packages/maistro-core/tests/agents/test_turn_usage_is_counted.py
  - packages/maistro-core/tests/persistence/test_outcome_usage_count.py
source:
  - packages/maistro-core/src/maistro/capabilities/invocation.py
  - packages/maistro-core/src/maistro/capabilities/invocation_store.py
  - packages/maistro-core/src/maistro/quota/usage_report.py
  - packages/maistro-core/src/maistro/agents/strategies/direct.py
  - packages/maistro-core/src/maistro/agents/strategies/react.py
  - packages/maistro-core/src/maistro/types/memory.py
ac-modules:
  AC-1: maistro.capabilities.invocation
  AC-2: maistro.capabilities.invocation_store
  AC-3: maistro.agents.strategies.direct
  AC-4: maistro.agents.strategies.react
  AC-5: maistro.types.memory
  AC-6: maistro.persistence.pg_outcomes
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-6cef: A turn reports the usage it was given, and the unreached layer says it is unreached

## Context

`grep -rn "send_invocation\|InvocationExecutionService(" packages/ | grep -v /tests/`
returns the definition and nothing else, and the strategies spell
`usage.get("prompt_tokens", 0)`. ADR-083026-aba1 records the decisions. This
spec states what has to be true.

One parser serves both halves of the second rule, and it is a leaf module
(`maistro.quota.usage_report`) rather than a function on `quota.recorder`:
importing the recorder from the agent strategies would make it, `quota.ambient`
and `quota.reconciliation` reachable, reporting three modules connected when
nothing wires any of them. Overstating reach while fixing an overstated
measurement is not a trade worth making.

## Decision

Two rules.

**A record nothing constructs says so.** The capability Invocation layer keeps
its semantics and gains a statement of its reach, naming #55. This is a
docstring rule with a test, not a convention: the test reads the real modules,
so the statement cannot rot away while the reach stays the same.

**A total says how many calls it summed.** `Outcome.usage_reported_calls`
counts the provider calls of a turn that returned a `usage` object. `None` when
the writer did not count; an integer otherwise. `0 tokens over 0 reporting
calls` and `0 tokens over 3 reporting calls` are different facts and stop being
the same stored number. The token fields stay `int`: the count beside the value
is ADR-083026-a91e's own shape, and making the value optional would ripple
through twenty-seven non-test files for a distinction the count already draws.

## Retention and scope

`usage_reported_calls` lives on the `Outcome` and shares its retention; it is
one small integer per turn. It carries no content and no identity, so it adds
nothing to what an outcome discloses.

## Consequences

### Positive
- The capability layer's reach is legible from the module.
- An unreported usage stops being stored as a measured zero.

### Negative / Trade-offs
- A count is not a per-call breakdown; that needs #55.

### Neutral
- Rows written before this change read as `None`, which is what they are.

## Acceptance Criteria

```gherkin
Feature: A turn reports the usage it was given, and the unreached layer says it is unreached

  @AC-1
  Scenario: The Invocation and its services state that nothing constructs them
    Given the capability invocation module
    When a reader looks for what constructs an Invocation in production
    Then the module says that nothing does, and names the issue that will
    And the statement covers the execution service and the governed one

  @AC-2
  Scenario: The Invocation store states that nothing wires it
    Given the capability invocation store
    When a reader looks for what constructs it in production
    Then the module says that nothing does
    And it says that its table has no migration, unlike the tables that do

  @AC-3
  Scenario: A direct turn counts the calls that reported usage
    Given a provider that returns a usage object on one call and none on another
    When a direct strategy completes the turn
    Then the totals sum only the usage that was reported
    And the turn reports that one call reported it
    And a turn where no call reported usage reports zero reporting calls, not zero tokens measured

  @AC-4
  Scenario: A multi-step turn counts every reporting call
    Given a react loop making three provider calls, two of which report usage
    When the turn completes
    Then the totals sum the two
    And the turn reports two reporting calls

  @AC-5
  Scenario: The record says its totals are a sum
    Given the Outcome record
    When a reader reads what its token fields mean
    Then it says they are a sum over the provider calls of one turn
    And the reporting-call count is absent rather than zero when the writer did not count

  @AC-6
  Scenario: The count survives the round trip on every backend
    Given an outcome carrying a reporting-call count
    When it is stored and read back
    Then the count comes back unchanged
    And an outcome written before the column existed reads back as absent
```
