---
id: SPEC-081226-9944
title: Canonical Product Hierarchy and Ownership
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
  - maistro-engine#ADR-081226-9944
implements:
  - maistro-engine#ADR-081226-9944
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-e626
  - maistro-engine#ADR-081226-a66b
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-core/src/maistro/workspaces
  - packages/maistro-core/src/maistro/projects
  - packages/maistro-core/src/maistro/personas
  - packages/maistro-core/src/maistro/graph
  - packages/maistro-core/src/maistro/runs
ac-modules:
  AC-1: maistro.workspaces.model
  AC-2: maistro.workspaces.store
  AC-3: maistro.graph.definitions
  AC-4: maistro.graph.definitions
  AC-5: maistro.runs.model
  AC-6: maistro.runs.store
  AC-7: maistro.personas.model
  AC-8: maistro.runs.service
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-9944: Canonical Product Hierarchy and Ownership

- **Status:** Active
- **Date:** 2026-08-14 revision
- **ADR:** `ADR-081226-9944`

## Canonical hierarchy

```text
User[] <- WorkspaceMembership -> Workspace[]
Workspace
├── exactly one live Persona
├── Workspace-wide Templates[]
└── exactly one Root Project
    ├── nested Project[]
    └── project-scoped durable objects
```

Execution:

```text
Graph -> Node[]
Run -> NodeRun[] -> Attempt[] -> ExecutionRuntime
```

Capability fulfillment:

```text
Capability -> Provider -> Binding -> Invocation
```

## Requirements

1. Workspace MUST be the durable environment boundary and MUST NOT structurally require a single owning User.
2. Workspace membership MUST be represented separately from Workspace identity.
3. Every Workspace MUST have exactly one live Persona.
4. Persona MUST encode taste, style, purpose, and behavioral/default preferences rather than security authority.
5. Every Workspace MUST have exactly one persisted Root Project.
6. Project-scoped durable objects MUST identify exactly one Project in the same Workspace.
7. NodeTemplate and GraphTemplate MUST remain Workspace-wide reusable definitions rather than Project-filed objects.
8. Graph MUST be a project-scoped mutable composition object. Node definition MUST remain separate from NodeRun/Attempt execution state.
9. Run MUST be the universal logical execution identity and MUST preserve `workspace_id` and `project_id` from its captured Graph snapshot.
10. NodeRun MUST identify logical execution of a Node; Attempt MUST identify one physical try.
11. ExecutionRuntime MUST key physical work by Attempt identity and MUST not become the business lifecycle authority.
12. Session MUST remain distinct from Run and MAY span multiple Runs.
13. Capability, Provider, Binding, and Invocation MUST remain separate from Run lifecycle and Project ownership concepts.
14. Existing package-specific AgentRun/GraphRun/DurableRun/Task lifecycles MUST migrate toward the canonical execution hierarchy rather than become new universal lifecycle classes.

## Acceptance Criteria

```gherkin
Feature: Canonical product hierarchy and ownership

  @AC-1
  Scenario: Workspace identity is independent of its members
    Given a Workspace with one member
    When a second User is added through WorkspaceMembership
    Then both Users can reach the Workspace
    And the Workspace identity is unchanged

  @AC-2
  Scenario: Workspace creation provisions a Root Project
    Given no Workspace exists
    When a Workspace is created
    Then exactly one persisted Root Project exists in it
    And a live Persona can be attached without granting any membership

  @AC-3
  Scenario: One Workspace Template instantiates into several Projects
    Given a Workspace-wide Template and two Projects in that Workspace
    When the Template is instantiated into each Project
    Then each Project holds its own mutable object
    And the Template itself is neither moved nor duplicated

  @AC-4
  Scenario: A persisted Graph carries both scopes
    Given a Graph saved in a Project
    When the Graph is reloaded
    Then it reports both its workspace_id and its project_id

  @AC-5
  Scenario: A Run captures scope immutably from its Graph snapshot
    Given a Graph in a known Workspace and Project
    When a Run is created from it
    Then the Run records that workspace_id and project_id
    And later edits to the Graph do not change the Run's recorded scope

  @AC-6
  Scenario: Retry adds an Attempt rather than a Run
    Given a Run with a failed NodeRun
    When the NodeRun is retried
    Then the Run id and NodeRun id are unchanged
    And a new Attempt exists with the next ordinal

  @AC-7
  Scenario: Persona configures taste, never authority
    Given a Persona on a Workspace
    When its fields are used to build an execution context
    Then no permission is granted by any Persona field
    And no credential or resource becomes reachable that was not already authorized

  @AC-8
  Scenario: Ordinary child Run creation cannot leave the Workspace
    Given a Run in one Workspace
    When a child Run is requested in a different Workspace through the ordinary execution API
    Then the request is refused

  @AC-9
  Scenario: A competing universal Run lifecycle is a violation
    Given the architecture fitness check
    When a second universal run-lifecycle definition is introduced
    Then the check reports it as a violation
```

## Non-goals

This SPEC delegates Project-tree details to `SPEC-081426-b1d3`, execution mechanics to `SPEC-081426-1f7c`, and authorization resolution details to `SPEC-081226-6e34`.
