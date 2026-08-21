---
id: SPEC-081226-6e34
title: Scoped Grants and Deny-Wins Authorization
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
  - maistro-engine#ADR-081226-6e34
implements:
  - maistro-engine#ADR-081226-6e34
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-9944
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
  - packages/maistro-core/src/maistro/security
ac-modules:
  AC-1: maistro.projects.authorization
  AC-2: maistro.projects.authorization
  AC-3: maistro.projects.authorization
  AC-4: maistro.projects.authorization
  AC-5: maistro.projects.authorization
  AC-6: maistro.projects.authorization
  AC-7: maistro.projects.authorization
  AC-8: maistro.projects.authorization
  AC-9: maistro.projects.authorization
  AC-10: maistro.personas.model
  AC-11: maistro.projects.authorization
  AC-12: maistro.capabilities.registry
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-6e34: Scoped Grants and Deny-Wins Authorization

- **Status:** Active
- **Date:** 2026-08-14 revision
- **ADR:** `ADR-081226-6e34`

## Authorization inputs

Effective authorization for a principal operating on a project-scoped object MUST be resolvable from structural data including:

```text
Principal
WorkspaceMembership
Project ancestry
ProjectMembership / scoped grants
object-specific grants where supported
explicit denies
Policies
resource visibility
```

Persona is not an authorization input.

## Requirements

### R1. Scope containment

Every grant/deny MUST have a scope. A Project-scoped grant or deny applies only to that Project and descendants. No Project authorization record may leak to siblings, ancestors, another Workspace, or otherwise outside its declared scope.

### R2. Additive grants

All applicable grants MUST accumulate. A narrower scope MAY add actions unavailable at a broader scope.

### R3. Deny wins

All applicable denies MUST accumulate. If an action/resource selector is both granted and denied, the deny MUST win regardless of which applicable scope supplied the grant.

### R4. No grant-around-deny

A grant created below the scope of an inherited deny MUST NOT restore the denied action/resource.

### R5. Workspace boundary

Cross-Workspace authorization MUST fail closed by default. Project membership never creates Workspace membership or access to another Workspace.

### R6. Resource visibility

Project-scoped resource visibility MUST be evaluated before use. A resource attached to an ancestor is available downward; a child resource is not available upward or sideways. An action grant MUST NOT by itself make an otherwise invisible resource visible.

### R7. Explicit delegation

Delegating/granting authority MUST require an explicit delegation permission or equivalent rule for the target action/scope. Possessing action X MUST NOT imply permission to grant X.

### R8. Role bundles

Named roles such as Workspace `owner`, `contributor`, and `member` MAY expand into grant bundles for convenience. Roles MUST NOT replace granular grant/deny evaluation or be treated as a universal total ordering across different scopes.

### R9. Persona independence

Changing Persona purpose, taste, style, preferred Provider/Binding, defaults, or product surfaces MUST NOT change the principal's structural grants/denies or resource visibility.

### R10. Invocation authorization

Before a Binding/Provider/Invocation uses a Project-scoped resource, the authorization path MUST verify both required action authority and resource visibility. Provider fallback MUST NOT escape the Binding/resource authorization already established.

## Acceptance Criteria

```gherkin
Feature: Hierarchical permissions

  @AC-1
  Scenario: Grants accumulate inside their scope only
    Given a principal with Workspace member and Project A contributor
    When effective grants are resolved inside Project A
    Then both grant sets apply
    But outside Project A only the Workspace grants apply

  @AC-2
  Scenario: A sibling Project sees no grant from its sibling
    Given a grant made in Project A
    When grants are resolved in sibling Project B
    Then the grant from A does not appear

  @AC-3
  Scenario: A child may grant authority its parent lacks
    Given a Workspace whose grants exclude publish
    When child Project A grants publish
    Then publish is effective inside A's subtree
    And it is not effective outside that subtree

  @AC-4
  Scenario: A Root deny beats a descendant grant
    Given a Root deny of publish
    When a descendant Project grants publish
    Then publish is not effective

  @AC-5
  Scenario: An object-specific deny beats scope grants
    Given applicable Workspace and Project grants for an action
    When an object-specific deny covers that object
    Then the action is refused on it

  @AC-6
  Scenario: A child Credential is invisible to its parent
    Given a Credential scoped to a child Project
    When a principal with a broad credential-use grant resolves it from the parent
    Then the Credential is unavailable

  @AC-7
  Scenario: Holding a permission is not authority to delegate it
    Given a principal with publish but no delegation authority
    When it grants publish to another principal
    Then the grant is refused

  @AC-8
  Scenario: Delegation authority is itself scoped
    Given a Project administrator with grant:publish for Project A
    When it grants publish inside A
    Then the grant succeeds
    But the same grant in a sibling Project is refused

  @AC-9
  Scenario: Cross-Workspace references are rejected
    Given a Project or grant reference naming another Workspace
    When it is resolved
    Then it is rejected

  @AC-10
  Scenario: Persona changes never change authorization
    Given fixed membership, grant and deny inputs
    When the Persona is modified
    Then authorization resolves identically

  @AC-11
  Scenario: Role bundles expand and remain deniable
    Given a role bundle assigned to a principal
    When authorization resolves
    Then the bundle expands into granular grants
    And an explicit deny still constrains them

  @AC-12
  Scenario: Fallback cannot escape the authorized candidate set
    Given a Binding whose Provider fails
    When fallback selects a replacement
    Then the replacement is inside the authorized and visible candidate set
```

## Non-goals

This SPEC does not prescribe the persistence schema for grants/denies, the complete action vocabulary, policy-expression language, approval UX, or Warden/Sentinel internal algorithms.
