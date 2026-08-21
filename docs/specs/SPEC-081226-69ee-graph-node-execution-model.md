---
id: SPEC-081226-69ee
title: Graph and Node Execution Model
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
  - maistro-engine#ADR-081226-69ee
implements:
  - maistro-engine#ADR-081226-69ee
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081426-1f7c
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-core/src/maistro/graph
  - packages/maistro-core/src/maistro/runs
ac-modules:
  AC-1: maistro.graph.definitions
  AC-2: maistro.graph.definitions
  AC-3: maistro.graph.definitions
  AC-4: maistro.graph.definitions
  AC-5: maistro.graph.dag_validator
  AC-6: maistro.graph.definitions
  AC-7: maistro.runs.store
  AC-8: maistro.runs.store
  AC-9: maistro.graph.node_types
  AC-10: maistro.runs.service
  AC-11: maistro.runs.service
  AC-12: maistro.runs.service
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-69ee: Graph and Node Execution Model

- **Status:** Active
- **Date:** 2026-08-14 revision
- **ADR:** `ADR-081226-69ee`

## Required model

```text
Workspace-wide GraphTemplate
        |
        | instantiate into Project
        v
Project-scoped Graph
├── Node[]
└── Edge[]

Run
├── immutable GraphSnapshot(workspace_id, project_id)
├── GraphExecutionState
└── NodeRun[] -> Attempt[] -> ExecutionRuntime
```

## Requirements

1. A Graph MUST support one or more Nodes; one Node is valid.
2. A persisted Graph MUST contain non-empty `workspace_id` and `project_id` values.
3. The Graph's Project MUST belong to the Graph's Workspace.
4. Node IDs MUST be unique within a Graph and Edges MUST reference Nodes in that Graph.
5. GraphTemplate MUST remain Workspace-wide and MUST NOT carry destination Project filing as Template identity.
6. GraphTemplate instantiation MUST require a destination Project in the same Workspace and record exact Template provenance on the resulting Graph.
7. Run creation MUST capture Graph identity, Workspace identity, Project identity, stable content hash, and serialized Graph definition.
8. Editing or moving a Graph after Run creation MUST NOT change the captured Run snapshot.
9. Node definition MUST contain NodeType/configuration and MUST NOT contain live Run/Attempt state.
10. Traversal selection of a Node MUST create/use a canonical NodeRun; physical work MUST occur through Attempt.
11. Repeated traversal of the same Node MAY create another NodeRun with a new NodeRun identity/ordinal in the same Run.
12. NodeType implementations MUST NOT persist/own an independent universal Run lifecycle.
13. GraphExecutionState MUST be separable from Run and MUST contain graph-specific traversal state only.
14. Edge predicates/conditional routing MUST be evaluated by graph/domain logic, not ExecutionRuntime.
15. Fanout/fanin readiness MUST be decided by graph/domain logic; Runtime MAY enforce bounded concurrency after Nodes are declared ready.
16. A subgraph Node SHOULD create a child Run with parent/NodeRun correlation and an immutable target snapshot.
17. A child Run MUST default to its parent's Project unless an explicit same-Workspace destination Project is requested and authorized.
18. Child Runs MUST NOT cross Workspace boundaries through ordinary execution APIs.
19. `GraphConfig`, `GraphRun`, `DurableRunRecord`, `DurableNodeRecord`, and equivalent duplicate lifecycle types are removal targets, not compatibility contracts.

## NodeType registry contract

A NodeType registration MUST declare enough metadata for the domain layer to validate and dispatch it, including a stable type identifier, configuration/schema contract, and executor/binding strategy. Registration MUST NOT grant permissions by itself.

Initial canonical categories:

- `agent`
- `api`
- `capability` with `tool` alias
- `harness`
- `human`
- `evaluation`
- `transform`
- `control` with `router` alias
- `subgraph`

Package-specific types MAY extend the registry.

## Acceptance Criteria

```gherkin
Feature: Graph and Node execution model

  @AC-1
  Scenario: A one-node Graph captures into a Run snapshot
    Given a project-scoped Graph with one Node
    When a Run is created from it
    Then the Run holds a snapshot of that Graph

  @AC-2
  Scenario: The snapshot is immune to later edits
    Given a Run created from a Graph
    When the Graph is edited or moved to another Project
    Then the Run's snapshot, its materialized definition, and its captured Project identity are unchanged

  @AC-3
  Scenario: An unscoped Graph is rejected
    Given a Graph with no Workspace or no Project
    When it is persisted
    Then it is rejected

  @AC-4
  Scenario: A Graph cannot point at a Project in another Workspace
    Given a Graph whose Project belongs to a different Workspace
    When it reaches the canonical persistence boundary
    Then it is rejected

  @AC-5
  Scenario Outline: Malformed topology is rejected
    Given a Graph containing <defect>
    When it is validated
    Then it is rejected

    Examples:
      | defect                              |
      | duplicate Node IDs                  |
      | an Edge targeting an external Node  |

  @AC-6
  Scenario: Template instantiation needs a destination and yields independence
    Given a Workspace-wide GraphTemplate
    When it is instantiated without a destination Project
    Then instantiation is refused
    But with a destination Project it produces independent topology carrying provenance

  @AC-7
  Scenario: NodeRun creation rejects an unknown Node
    Given a Run whose snapshot does not contain a given Node ID
    When a NodeRun is created for that Node ID
    Then it is rejected

  @AC-8
  Scenario: Re-executing a Node creates distinct NodeRuns
    Given a Node executed once under a Run
    When the same Node executes again in that Run
    Then a second, distinct NodeRun exists under the same Run

  @AC-9
  Scenario: The Runtime receives ready work without interpreting predicates
    Given a NodeType under test
    When it hands work to the Runtime
    Then the Runtime neither imports nor interprets graph predicates

  @AC-10
  Scenario: A subgraph child Run inherits the Project
    Given a Run in a Project
    When a subgraph child Run is created with no destination given
    Then it records the parent's project_id

  @AC-11
  Scenario: Cross-Project child execution is explicit and authorized
    Given a destination Project in the same Workspace
    When cross-Project child execution is requested explicitly
    Then the destination Project is recorded
    And authorization is required at the service boundary

  @AC-12
  Scenario: Cross-Workspace child creation is rejected
    Given a destination Project in a different Workspace
    When child creation is requested
    Then it is rejected

  @AC-13
  Scenario: A NodeType executor cannot own Run persistence
    Given the architecture fitness checks
    When a NodeType executor writes Run persistence directly
    Then the checks detect it
```

## Non-goals

This SPEC does not define Project grant algorithms, Provider selection, durable Event envelopes, or UI graph-editor behavior.
