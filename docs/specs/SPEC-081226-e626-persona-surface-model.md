---
id: SPEC-081226-e626
title: Persona and Product Surface Model
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
  - maistro-engine#ADR-081226-e626
implements:
  - maistro-engine#ADR-081226-e626
related:
  - maistro-engine#ADR-081226-9944
  - maistro-engine#ADR-081426-b1d3
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
  - packages/maistro-core/src/maistro/personas
ac-modules:
  AC-1: maistro.personas.model
  AC-2: maistro.personas.model
  AC-3: maistro.personas.model
  AC-4: maistro.projects.authorization
  AC-5: maistro.personas.model
  AC-6: maistro.projects.authorization
  AC-7: maistro.personas.model
  AC-8: maistro.personas.model
  AC-9: maistro.personas.model
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-e626: Persona and Product Surface Model

- **Status:** Active
- **Date:** 2026-08-14 revision
- **ADR:** `ADR-081226-e626`

## Requirements

### R1. Cardinality

A Workspace MUST have at most one live Persona record at a time. Persona identity MUST be scoped to one Workspace.

### R2. Purpose, taste, and style

Persona MUST support explicit representation of purpose and configurable taste/style guidance. Implementations MAY structure these as typed fields, text guidance, or extensible settings, but the stored model MUST be able to express all three concerns distinctly.

### R3. Behavioral and creation defaults

Persona MAY define defaults used when creating new Workspace/Project objects or resolving ordinary behavior. These defaults are preference/configuration inputs and become ordinary object-owned configuration when applied at creation time.

### R4. Preferences

Persona MAY name preferred models, providers, capabilities, Bindings, prompts, parameters, or templates. A preference MUST NOT imply that the preferred resource is authorized or visible in the current Project.

### R5. Product surfaces

Persona MAY configure relevant product surfaces such as `ui`, `builders_cli`, and `builders_rsi`. Surface configuration controls product experience/exposure, not security authority.

### R6. No authorization semantics

Persona MUST NOT contain or compute:

- permission ceilings,
- security grants,
- explicit denies,
- Project membership,
- credential visibility,
- privilege elevation,
- authority widening or narrowing.

Authorization services MUST be able to resolve Principal authority without consulting Persona.

### R7. Agent separation

Persona MUST NOT own Run/NodeRun/Attempt state and MUST NOT be treated as an Agent actor. Agent behavior executes through Nodes/Graphs/Runs.

### R8. Project-default interaction

When creation defaults are resolved, Persona defaults MAY be applied after Workspace defaults and before Project ancestry defaults. Project defaults closer to the destination MAY override Persona defaults. Once created, the object owns the resolved configuration.

## Acceptance Criteria

```gherkin
Feature: Persona surface model

  @AC-1
  Scenario: Purpose is independent of name
    Given a Persona
    When its purpose is set
    Then the purpose is stored independently of the Persona name

  @AC-2
  Scenario: Taste and voice are separate fields
    Given a Persona
    When taste/aesthetic and style/voice guidance are set
    Then each is stored and readable independently

  @AC-3
  Scenario: Persona shapes surfaces, not permissions
    Given a principal with fixed grants
    When the Persona configures UI and Builders surfaces
    Then the principal's effective permissions are unchanged

  @AC-4
  Scenario: Preference cannot override authorization
    Given a Persona preferring Binding A
    When Project authorization makes only Binding B available
    Then Binding A remains unavailable

  @AC-5
  Scenario: Persona carries no authority fields
    Given the Persona schema
    When it is inspected
    Then it has no permission_ceiling, grant, deny, or credential-scope field

  @AC-6
  Scenario: Authorization is stable across Persona edits
    Given resolved authorization for a principal
    When Persona style, taste, purpose or preferences change
    Then authorization resolves to the same result

  @AC-7
  Scenario: Persona defaults apply at creation only
    Given a Persona with creation defaults
    When a new object is created
    Then the defaults participate in its resolution
    But a later Persona change does not mutate that existing object

  @AC-8
  Scenario: One live Persona per Workspace
    Given a Workspace with a live Persona
    When a second live Persona is attached
    Then the store or service refuses it

  @AC-9
  Scenario: Persona holds no execution state
    Given the Persona schema
    When it is inspected
    Then it contains no Run or Attempt lifecycle state
```

## Non-goals

This SPEC does not define Project authorization, Agent identity, Provider fallback, or the visual design of Persona-editing UI.
