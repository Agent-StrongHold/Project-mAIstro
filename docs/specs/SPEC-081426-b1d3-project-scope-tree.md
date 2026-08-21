---
id: SPEC-081426-b1d3
title: Project Scope Tree
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-14
history:
  - status: Proposed
    date: 2026-08-14
  - status: Accepted
    date: 2026-08-14
  - status: AC Defined
    date: 2026-08-14
substrate:
  - maistro-engine#ADR-081426-b1d3
implements:
  - maistro-engine#ADR-081426-b1d3
related:
  - maistro-engine#ADR-081226-9944
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
  - packages/maistro-core/src/maistro/projects
  - packages/maistro-core/src/maistro/workspaces
ac-modules:
  AC-1: maistro.projects.scope
  AC-2: maistro.projects.scope
  AC-3: maistro.projects.scope
  AC-4: maistro.projects.scope
  AC-5: maistro.projects.scope
  AC-6: maistro.projects.scope
  AC-7: maistro.projects.scope
  AC-8: maistro.projects.scope_store
  AC-9: maistro.projects.scope
  AC-10: maistro.projects.authorization
  AC-11: maistro.projects.authorization
  AC-12: maistro.projects.authorization
  AC-13: maistro.projects.authorization
  AC-14: maistro.projects.scope
  AC-15: maistro.projects.authorization
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081426-b1d3: Project Scope Tree

- **Status:** Active
- **Date:** 2026-08-14
- **ADR:** `ADR-081426-b1d3`

## Required model

```text
Workspace
├── Persona
├── Templates[]
└── Root Project
    ├── Project[]
    └── project-scoped objects/resources
```

## Requirements

### R1. Root Project

Creating a Workspace MUST create exactly one persisted Root Project in the same durable operation or an equivalent failure-atomic workflow. The Root Project MUST have a stable `project_id`, the Workspace's `workspace_id`, `parent_project_id = null`, and `is_root = true`.

Root creation MUST be idempotent for a Workspace. The Root Project MUST NOT be moved, deleted, or assigned a parent.

### R2. Project tree integrity

Every non-root Project MUST belong to exactly one Workspace and have exactly one parent Project in that Workspace. Project ancestry MUST be acyclic. Cross-Workspace parenting and moves MUST be rejected.

### R3. Project-scoped object membership

Every project-scoped durable object MUST carry a non-empty `project_id` whose Project belongs to the object's Workspace. Objects filed at the visible Workspace root use the Root Project's ID rather than a nullable Project reference.

### R4. Workspace-wide Templates

NodeTemplate and GraphTemplate MUST remain Workspace-owned and MUST NOT require Project membership. Template instantiation MUST require a destination Project in the same Workspace. The instantiated object MUST carry the destination `project_id` while preserving exact Template provenance.

### R5. Creation defaults

Creation defaults MUST resolve in this order:

```text
Workspace -> Persona -> Root Project -> ancestors -> destination Project
```

For each setting, the closest specified value wins. Resolved values become owned configuration on the new object. Later Project-default changes MUST NOT mutate existing objects. Moving an object MUST NOT reapply defaults.

### R6. Scoped resource visibility

A resource scoped to Project P MUST be visible to P and descendants of P only. It MUST NOT become visible to ancestors, siblings, or Projects outside P's subtree. Cross-Workspace resource visibility is denied by default.

### R7. Object moves

Moving an object MUST preserve its existing owned configuration. Before committing the move, the service MUST verify that every required scoped resource remains visible from the destination Project. If any required resource is unavailable, the move MUST fail atomically with the object's original Project unchanged.

### R8. Membership and grants

Workspace grants and all applicable Project grants from the destination object's ancestry MUST accumulate. A Project grant applies only within the Project subtree in which it was issued. A narrower Project MAY grant actions not granted at broader scopes.

### R9. Denies

Applicable explicit denies MUST accumulate. If an action/resource is both granted and denied, the deny wins. A descendant grant MUST NOT bypass a deny inherited from an ancestor scope.

Conceptually:

```text
effective authority = union(applicable grants) - union(applicable denies)
```

### R10. Delegation authority

Authority to perform an action MUST NOT imply authority to delegate that action. Grant/delegation authority MUST be explicit and scope-bound.

### R11. Project deletion

Root Project deletion MUST always fail. Non-root Project deletion MUST fail while the Project contains child Projects or durable project-scoped content/resources requiring explicit disposition. Deletion MUST NOT implicitly recursively delete, move, or reparent contained state.

### R12. Persona exclusion from authorization

Persona MUST NOT contribute grants, denies, credential visibility, or security authority. Persona preferences MAY select or prefer a capability/provider/binding only after Project/resource authorization has made it available.

## Acceptance Criteria

```gherkin
Feature: Project scope tree

  @AC-1
  Scenario: Root provisioning is idempotent
    Given a new Workspace
    When the Root Project is provisioned twice
    Then exactly one Root Project exists
    And both calls return the same Project

  @AC-2
  Scenario Outline: The Root Project is immovable
    Given a Workspace Root Project
    When it is <operation>
    Then the operation is refused

    Examples:
      | operation |
      | moved     |
      | deleted   |
      | parented  |

  @AC-3
  Scenario: The tree stays acyclic and inside one Workspace
    Given nested Projects
    When a parent/child link is created
    Then both must be in the same Workspace
    And a link forming a cycle is rejected

  @AC-4
  Scenario: A Graph at the Workspace root files under Root Project
    Given a Workspace with its Root Project
    When a project-scoped Graph is created at the root
    Then it carries the Root Project ID rather than a null project_id

  @AC-5
  Scenario: Instantiation files the copy without moving the Template
    Given a Workspace-wide GraphTemplate
    When it is instantiated into Project A
    Then the resulting Graph is filed in A
    And the Template remains Workspace-wide

  @AC-6
  Scenario: Defaults resolve nearest-wins and never act retroactively
    Given defaults set at several levels of the Project tree
    When an object is created
    Then the nearest default wins
    And changing a default later does not mutate that object

  @AC-7
  Scenario: Moving an object preserves its resolved configuration
    Given an object with resolved configuration
    When it is moved to another Project
    Then its configuration is byte-for-byte equivalent apart from filing and scope metadata

  @AC-8
  Scenario: Resource visibility follows the tree downward only
    Given a Credential at the Root and another in a child Project
    When visibility is resolved
    Then descendants see the Root resource
    But the Root and siblings do not see the child resource

  @AC-9
  Scenario: An impossible move changes nothing
    Given an object depending on a resource unavailable in the destination
    When the move is attempted
    Then it is rejected
    And the object keeps its original project_id

  @AC-10
  Scenario: Ancestor grants accumulate without leaking sideways
    Given grants at Workspace, ancestor and target Project
    When authorization resolves in the target Project
    Then all three accumulate
    And none apply in a sibling Project

  @AC-11
  Scenario: A narrower Project may hold stronger authority
    Given a Workspace without an authority
    When a descendant Project grants it
    Then it is effective inside that subtree only

  @AC-12
  Scenario: An inherited deny beats grants above and below
    Given an inherited deny for an action
    When both an inherited grant and a descendant grant exist for it
    Then the action is refused

  @AC-13
  Scenario: publish does not confer the right to delegate publish
    Given a principal holding publish
    When it grants publish to another principal
    Then the grant is refused

  @AC-14
  Scenario: A non-empty Project is not deleted implicitly
    Given a Project containing objects
    When deletion is requested without explicit handling of its contents
    Then deletion is refused

  @AC-15
  Scenario: Persona cannot manufacture authorization
    Given Project and Workspace grants that exclude an action
    When the Persona is configured to prefer it
    Then the action remains unauthorized
```

## Migration guidance

The existing Project package MUST be re-audited piece-by-piece. Matching tree/resource behavior may be refactored into this model. Existing assumptions that Project is the Workspace ownership root MUST be removed rather than preserved through compatibility facades.

## Non-goals

This SPEC does not define UI folder presentation, graph traversal, Run state transitions, Provider selection algorithms, or the storage technology used for Project persistence.
