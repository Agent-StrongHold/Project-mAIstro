---
id: SPEC-081226-bb3a
title: Template, Object and Provenance Semantics
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
  - maistro-engine#ADR-081226-bb3a
implements:
  - maistro-engine#ADR-081226-bb3a
related:
  - maistro-engine#ADR-081226-9944
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/test_graph_definitions.py
source:
  - packages/maistro-core/src/maistro/graph/definitions.py
ac-modules:
  AC-1: maistro.graph.definitions
  AC-2: maistro.graph.definitions
  AC-3: maistro.graph.definitions
  AC-4: maistro.graph.definitions
  AC-5: maistro.graph.definitions
  AC-6: maistro.graph.definitions
  AC-7: maistro.graph.definitions
  AC-8: maistro.personas.model
  AC-9: maistro.graph.definitions
  AC-10: maistro.graph.definitions
  AC-11: maistro.graph.templates
  AC-12: maistro.graph.definitions
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-bb3a: Template, Object and Provenance Semantics

- **Status:** Active
- **Date:** 2026-08-12
- **ADR:** `ADR-081226-bb3a`
- **Technical Area:** Reusable definitions, workspace objects, provenance, versioning

## Purpose

Define executable semantics for `NodeTemplate -> Node` and `GraphTemplate -> Graph` so reusable MAIstro definitions are versioned and reproducible while instantiated Workspace objects remain independently editable.

## Canonical model

```text
Workspace
├── NodeTemplate[]
│   └── immutable Version[]
├── GraphTemplate[]
│   └── immutable Version[]
├── Node/Graph mutable objects
└── Persona[]
    └── template catalog visibility/references
```

Instantiation:

```text
NodeTemplate@version  --copy + provenance--> Node
GraphTemplate@version --copy + provenance--> Graph
```

## Required identifiers and provenance

A canonical template version MUST expose enough information to identify a stable snapshot:

```text
template_id
version
content_hash
```

A canonical instantiated object MUST retain at least:

```text
source_template_id
source_template_version
source_template_hash
```

An implementation MAY use a structured `TemplateProvenance` value rather than separate columns as long as these semantics are available.

## Requirements

### R1. Stable logical template identity

A template MUST have a stable `template_id` across its versions.

Creating a materially changed reusable definition under the same logical template MUST create a new version rather than overwrite historical version content.

### R2. Immutable historical versions

After a template version is published/persisted as an addressable version, its effective content MUST be immutable.

Metadata that does not alter semantic content MAY be appended where storage design requires it, but changing effective content MUST produce a new version/content hash.

### R3. NodeTemplate instantiation

Instantiating `NodeTemplate@V` MUST:

1. create a new Node identity;
2. copy/materialize the effective Node definition from exactly version `V`;
3. persist source template ID/version/hash;
4. attach the Node to the target Workspace/Graph context;
5. leave future Node edits independent from the template.

### R4. GraphTemplate instantiation

Instantiating `GraphTemplate@V` MUST:

1. create a new Graph identity;
2. create/materialize its Nodes and Edges from exactly version `V`;
3. persist Graph source template ID/version/hash;
4. preserve useful per-Node source provenance where the GraphTemplate originated those Nodes from NodeTemplates;
5. ensure future Graph/Node edits are independent from the template.

### R5. No floating nested template meaning

A persisted GraphTemplate version MUST NOT semantically depend on an unversioned/latest NodeTemplate reference.

Nested NodeTemplate dependencies MUST be represented by exact version references or by embedded effective snapshots.

### R6. Template update isolation

Publishing `NodeTemplate@V+1` or `GraphTemplate@V+1` MUST NOT mutate any Node/Graph instantiated from `V`.

No background migration may alter existing instances solely because a source template has a newer version.

### R7. Object mutation

A Node or Graph instantiated from a template MAY be edited without creating a template version.

Editing the object MUST retain original source provenance.

The implementation SHOULD expose whether the current object content differs from its source snapshot, using content comparison/hash where practical.

### R8. Save as new template

Saving a Node or Graph as a new template MUST create a new template identity with an initial immutable version and provenance back to the source object.

The source object MUST remain unchanged by the save operation.

### R9. Publish as new version

Publishing a Node or Graph as a new version of an existing template MUST:

1. require authorization for that template;
2. create a new immutable version under the existing template ID;
3. record provenance to the source object and prior template lineage as applicable;
4. leave prior versions and prior instances unchanged.

### R10. Persona catalogs

Persona template catalogs MUST reference templates available in its Workspace/product context rather than copy live template state into Persona.

Adding/removing a template from a Persona catalog changes availability/visibility only. It MUST NOT mutate the template or instantiated Nodes/Graphs.

### R11. Global/enterprise templates

If global/enterprise templates are supported, their scope MUST be explicit.

Instantiating a global/enterprise template into a Workspace MUST still copy/materialize the selected version and persist provenance. Workspace objects MUST NOT become mutable children of global definitions.

### R12. Runtime-state exclusion

Canonical NodeTemplate and GraphTemplate persisted semantic content MUST NOT contain mutable live execution fields including Run/NodeRun/Attempt identifiers, terminal state, retry counters or runtime cancellation/deadline state.

Defaults/policies that influence future execution MAY be stored as definition data.

### R13. Legacy adapter provenance

When an existing definition format is imported/projected into a canonical template, the canonical template MUST retain source-format provenance sufficient to identify the original type/source/version where available.

Adapters MUST NOT pretend an execution-time AgentSpec/Task record is a reusable template without first separating runtime fields.

### R14. Improvement/promotion

An improvement produced by RSI/Evolve/learning MUST be represented as a candidate object/template version before it becomes an active reusable version.

Promotion MUST be explicit and auditable according to applicable policy. Historical template versions and existing instantiated objects remain unchanged.

## Acceptance Criteria

```gherkin
Feature: Template / object provenance semantics

  @AC-1
  Scenario: Editing an instantiated Node leaves its Template untouched
    Given a Node instantiated from NodeTemplate T@1
    When the Node is edited
    Then T@1 is semantically unchanged
    And the Node still identifies T@1 through its source_template fields

  @AC-2
  Scenario: Publishing a new version does not disturb existing objects
    Given two Nodes instantiated from T@1
    When T@2 is published
    Then both Nodes are unchanged until an explicit update is invoked

  @AC-3
  Scenario: Instantiation binds to an exact version
    Given NodeTemplate versions T@1 and T@2
    When one Node is instantiated from each
    Then each materializes its own version's definition
    And each carries that version and hash as provenance

  @AC-4
  Scenario: Editing an instantiated Graph leaves its Template untouched
    Given a Graph instantiated from GraphTemplate GT@1
    When one Node and one Edge in the Graph are mutated
    Then GT@1 is unchanged

  @AC-5
  Scenario: A GraphTemplate version pins its nested NodeTemplates
    Given a published GraphTemplate that uses a NodeTemplate
    When the NodeTemplate is updated afterward
    Then re-instantiating the same GraphTemplate version produces the same effective graph definition as before

  @AC-6
  Scenario: Save-as-template creates a new identity and leaves the source alone
    Given a customized Node
    When it is saved as a new NodeTemplate
    Then a new template identity and version exist
    And their provenance identifies the source Node
    And the Node itself is unchanged

  @AC-7
  Scenario: Publishing a version keeps the old one addressable
    Given a customized object published as a new version of an existing template
    When the new version exists
    Then the previous version is still addressable and unchanged

  @AC-8
  Scenario: Persona catalog membership mutates nothing
    Given a template in a Persona catalog
    When it is added or removed from that catalog
    Then the template content and every instantiated object are unchanged

  @AC-9
  Scenario: Execution state is not reusable semantic content
    Given live Run, NodeRun or Attempt state supplied as template content
    When canonical template validation runs
    Then the state is rejected, or stripped into a non-template projection

  @AC-10
  Scenario Outline: Legacy definitions import with provenance
    Given an existing reusable <kind> definition
    When it is projected into its canonical template representation
    Then the result preserves source provenance

    Examples:
      | kind           |
      | agent          |
      | graph/workflow |

  @AC-11
  Scenario: Improvement produces candidates, never silent mutation
    Given a published template version and an improvement path
    When the path proposes an improvement
    Then a candidate version is produced
    And the published version is unchanged
    And promotion creates a new explicit version only after the policy gate

  @AC-12
  Scenario: Templates and provenance survive restart
    Given a persisted template version and an object instantiated from it
    When persistence is reloaded
    Then the immutable template snapshot and the object's source provenance resolve identically
```

## Migration guidance

Initial adapters should prioritize the highest-overlap reusable-definition families:

1. AgentIdentity / agent YAML / AgentCard projections
2. graph configs and recipes
3. PM fleet definitions
4. Builders workers/stages/workflows
5. imported agent/skill formats
6. domain-specific design/Canvas templates where they map cleanly

Do not delay canonical semantics until every legacy format is migrated. Introduce adapters and migrate consumers incrementally.

## Non-goals

This specification does not define:

- NodeType registry behavior;
- Run/NodeRun/Attempt lifecycle;
- exact permission intersection algorithm;
- a generic registry implementation;
- physical package renames;
- automatic three-way template-to-instance merge UX;
- mandatory global template marketplace behavior.

## References

- `ADR-081226-bb3a`
- `ADR-081226-9944`
- `docs/analysis/ECOSYSTEM-INVENTORY.md`
- `docs/analysis/ARCHITECTURE-CONVERGENCE-MATRIX.md`
