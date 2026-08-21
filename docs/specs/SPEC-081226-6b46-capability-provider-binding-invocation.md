---
id: SPEC-081226-6b46
title: Capability, Provider, Binding and Invocation
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-12
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
  - status: AC Defined
    date: 2026-08-12
substrate:
  - maistro-engine#ADR-081226-6b46
implements:
  - maistro-engine#ADR-081226-6b46
related:
  - maistro-engine#ADR-081226-6e34
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-core/src/maistro/capabilities
ac-modules:
  AC-1: maistro.capabilities.registry
  AC-2: maistro.capabilities.registry
  AC-3: maistro.capabilities.registry
  AC-4: maistro.capabilities.governed_invocation
  AC-5: maistro.capabilities.governed_invocation
  AC-6: maistro.capabilities.providers.harness_stub
  AC-7: maistro.credentials.store
  AC-8: maistro.capabilities.registry
  AC-9: maistro.runs.service
  AC-10: maistro.capabilities.harness_manager
  AC-11: maistro.capabilities.invocation_store
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-6b46: Capability, Provider, Binding and Invocation

- **Status:** Active
- **Date:** 2026-08-12
- **ADR:** `ADR-081226-6b46`

## Required relationships

```text
Node -> Binding -> Capability
                 -> allowed Provider set
Invocation -> selected Provider
```

## Requirements

1. Capability MUST have a stable semantic identifier/contract independent of provider implementation.
2. Provider MUST declare which Capability it implements and its protocol/health metadata.
3. Provider registration MUST NOT grant consumer authorization.
4. Binding MUST identify Workspace/global scope, Capability, allowed/pinned providers/config and credential references as applicable.
5. Node/Persona use of a Binding MUST be permission-checked before Invocation.
6. Provider selection MUST occur within Binding constraints; health fallback MUST NOT select an unauthorized provider.
7. Invocation MUST have a stable `invocation_id` and record selected Binding/Provider plus Run/NodeRun/Attempt correlation when executed in a Run.
8. Invocation MUST NOT persist resolved secret values.
9. ToolExposure MUST be generated/validated from an authorized Binding and MUST route model tool requests back through Binding/Invocation.
10. Protocol adapters MUST NOT define an independent universal execution lifecycle.
11. Agent-backed Binding invocation MUST create a correlated child Run for delegated work.
12. Harness/session handles MAY persist for provider protocol needs but MUST remain correlated to canonical execution.
13. Provider/circuit health MUST be observable separately from Run status.
14. Binding/Node policy MAY define retry/fallback constraints; Runtime only performs mechanics.
15. Existing tools, MCP, HTTP, sandbox, renderer, image and integration adapters MAY migrate incrementally behind compatibility adapters.

## Acceptance Criteria

```gherkin
Feature: Capability / Provider / Binding / Invocation

  @AC-1
  Scenario: Two Providers can serve one Capability
    Given a Capability with Provider A registered
    When Provider B is registered for the same Capability
    Then both are registered
    And the Capability identity is unchanged

  @AC-2
  Scenario: A constrained Binding never falls back
    Given a Binding constrained to Provider A
    When Provider A is unavailable and Provider B is healthy
    Then the Invocation does not use Provider B

  @AC-3
  Scenario: A permissive Binding selects a healthy allowed Provider and records it
    Given a Binding allowing Providers A and B
    When an Invocation is made
    Then an allowed healthy Provider is selected
    And the Invocation record names the selected provider

  @AC-4
  Scenario: Losing permission stops Invocation
    Given a Binding whose permission is removed
    When an Invocation is attempted
    Then it is refused
    And the refusal stands even though the Provider is still registered and healthy

  @AC-5
  Scenario: A model tool call routes through the same Binding
    Given a tool schema exposed to a model
    When the model calls that tool
    Then the call passes the same Binding authorization as any other Invocation
    And an Invocation record is produced

  @AC-6
  Scenario Outline: Every adapter satisfies one correlation contract
    Given a <adapter> adapter for a Provider
    When it executes an Invocation
    Then the Invocation carries the same correlation fields as any other adapter

    Examples:
      | adapter        |
      | HTTP/MCP       |
      | local function |

  @AC-7
  Scenario: Credentials are resolved at execution and never persisted
    Given a Binding referencing a credential
    When the Invocation executes
    Then the credential is resolved from its reference at execution time
    And no secret value appears in persisted Graph, Node, or Invocation data

  @AC-8
  Scenario: Provider health failure does not disturb Run identity
    Given a Binding allowing fallback and a Provider whose circuit opens
    When the Invocation falls back to an allowed Provider
    Then the Run identity is unchanged

  @AC-9
  Scenario: An agent-backed Binding creates a correlated child Run
    Given a Binding backed by an agent
    When it is invoked
    Then a child Run is created
    And it correlates to the parent Run and the Invocation
    And no A2A-only task lifecycle is used in its place

  @AC-10
  Scenario: A harness session keeps its handle without owning lifecycle
    Given a harness session executing under an Invocation
    When the session reports progress
    Then it retains its external handle
    And Run, NodeRun and Attempt remain the authoritative lifecycle records

  @AC-11
  Scenario Outline: Invocations are queryable by correlation id
    Given recorded Invocations
    When observability queries by <field>
    Then the matching Invocations are returned

    Examples:
      | field        |
      | workspace_id |
      | run_id       |
      | node_run_id  |
      | attempt_id   |
      | binding_id   |
      | provider_id  |

  @AC-12
  Scenario: An adapter cannot widen its parent Binding's permission
    Given the architecture tests
    When a provider or tool adapter widens the permission of its parent Binding
    Then the tests reject it
```

## Non-goals

This SPEC does not define the hierarchical permission algorithm, exact credential store, capability marketplace UX or provider-specific protocol implementation details.
