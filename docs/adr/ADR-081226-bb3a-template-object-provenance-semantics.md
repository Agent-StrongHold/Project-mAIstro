---
id: ADR-081226-bb3a
title: Template, Object and Provenance Semantics
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
substrate: []
implements: []
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
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-081226-bb3a: Template, Object and Provenance Semantics

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** MAIstro maintainers
- **Technical Area:** Reusable definitions, workspace objects, provenance, versioning

## Context

MAIstro currently has many reusable-definition formats: AgentIdentity, AgentCard, agent YAML, recipes, PM fleet definitions, graph configs, Builders workers/stages, skills, imported agents, design skills and domain-specific workflow definitions. Several of these blur the difference between a reusable definition and a live editable object.

That ambiguity causes two architectural problems:

1. changing a reusable definition can accidentally imply changing already-created work; and
2. execution-time fields such as task IDs, attempts, mutable context and runtime status leak into definitions that should be reusable.

The canonical hierarchy requires a clear Template -> Object boundary:

```text
NodeTemplate  -> Node
GraphTemplate -> Graph
```

Workspace remains the durable ownership root. Persona controls which templates/surfaces are available in a given product context, but template availability must not create an independent lifecycle authority.

## Decision

### 1. Templates are reusable definitions; Nodes and Graphs are editable objects

A `NodeTemplate` is a reusable definition from which a Node can be instantiated.

A `GraphTemplate` is a reusable definition from which a Graph can be instantiated.

A `Node` and `Graph` are mutable Workspace objects. They are not live children of their source template after instantiation.

### 2. Instantiation is copy plus provenance

Instantiation MUST materialize the selected template version into a new independent object.

The new object retains source provenance, including at least:

```text
source_template_id
source_template_version
source_template_hash
```

Implementations may additionally record:

```text
instantiated_at
instantiated_by
source_scope
source_import_provenance
```

Source provenance is historical evidence, not a live inheritance pointer.

### 3. Existing objects never change silently when a template changes

Publishing or creating a new template version MUST NOT mutate existing Nodes or Graphs instantiated from an earlier version.

An existing object may adopt changes only through an explicit user/system operation that produces an observable mutation and provenance record.

There is no implicit "follow latest template" behavior for canonical mutable objects.

### 4. Template versions are immutable snapshots

A template has a stable logical template identity and immutable version snapshots.

Conceptually:

```text
Template
├── template_id
└── Version[]
    ├── version
    ├── content
    ├── content_hash
    ├── created_at
    └── provenance
```

Changing reusable template content creates a new version. It does not rewrite an existing version in place.

The exact storage schema may represent this as separate records or another persistence shape, but externally visible semantics MUST preserve immutable historical versions.

### 5. GraphTemplate versions cannot contain floating semantic dependencies

A GraphTemplate version that depends on NodeTemplates MUST either:

1. embed the effective node definition in the GraphTemplate snapshot; or
2. reference an exact immutable NodeTemplate version.

It MUST NOT depend on an unpinned "latest" NodeTemplate version in a way that changes the meaning of an existing GraphTemplate version over time.

When a Graph is instantiated, each resulting Node should retain useful source provenance for both the GraphTemplate and any NodeTemplate from which that node definition originated.

### 6. Save-as-template is explicit

A mutable Node or Graph does not automatically become a reusable template.

Canonical operations include:

```text
instantiate NodeTemplate -> Node
instantiate GraphTemplate -> Graph
save Node as new NodeTemplate
save Graph as new GraphTemplate
publish Node as new version of an existing NodeTemplate
publish Graph as new version of an existing GraphTemplate
```

Creating a new version of an existing template requires explicit authorization and identifies the source object/version that produced it.

### 7. Template provenance survives object mutation

Editing an instantiated Node or Graph does not erase its source provenance.

The object may diverge arbitrarily from the source template. Provenance means "this object originated from this version", not "this object is still equal to this version".

Implementations SHOULD be able to determine whether the current object content still matches the source snapshot through hashes or equivalent comparison, but equality is not required for provenance retention.

### 8. Workspace owns templates; Persona exposes template catalogs

Workspace is the default durable owner/scope for user-created templates.

Persona contains or references the NodeTemplate and GraphTemplate catalogs visible/available through that Persona. Persona catalog membership is an availability/product-surface concern, not an alternative template persistence root.

Platform-global or enterprise template catalogs may exist, but they must have explicit ownership/scope and authorization rules. They are not implicitly owned by every Workspace.

### 9. Execution state does not belong in templates

Template content may describe execution configuration, policies and defaults, but MUST NOT contain mutable execution identity/state such as:

- Run ID
- NodeRun ID
- Attempt ID
- current Run status
- retry counters for a live execution
- runtime cancellation state
- mutable execution timestamps

Those belong to Run/NodeRun/Attempt/Invocation.

### 10. Existing reusable formats migrate through projections/adapters

Existing assets such as AgentIdentity, AgentCard, recipes, PM fleet definitions, Builders worker/stage registrations and imported external agent/skill formats do not need to disappear immediately.

Each must be classified as one or more of:

- NodeTemplate projection
- GraphTemplate projection
- PromptTemplate/ParameterSet/Schema asset
- Capability/Binding declaration
- import/export portability format
- package-specific reusable domain asset

Adapters may preserve current public formats while canonical template services become authoritative.

### 11. Evolution and improvement produce candidate template versions, not silent mutation

RSI/Evolve/learning systems may produce improved candidate definitions from execution outcomes.

The canonical flow is:

```text
existing object/template
-> execute/evaluate
-> improvement candidate
-> review/policy gate if required
-> explicit new template version
```

They MUST NOT silently mutate an active object or historical template version as the mechanism of learning/promotion.

## Consequences

### Positive

- Existing work is stable even as reusable templates improve.
- Template provenance becomes inspectable and auditable.
- Agent/graph definitions stop carrying live execution state.
- Evolve/RSI can produce safe candidate versions without rewriting active work.
- Persona template catalogs can become product UX without becoming another persistence root.
- Imported formats can coexist as projections during migration.

### Negative

- Version records and provenance add persistence complexity.
- Existing formats that currently mix definition and runtime state require decomposition.
- GraphTemplate publishing must snapshot or pin nested template dependencies.
- Applying template updates to existing objects requires an explicit future UX/merge operation rather than automatic inheritance.

### Neutral

- This ADR does not require all templates to be globally discoverable.
- This ADR does not require content-addressed storage, though content hashes are strongly useful.
- This ADR does not define how Persona permissions are evaluated.
- This ADR does not make every reusable domain asset a NodeTemplate or GraphTemplate.

## Alternatives Considered

### Live inheritance from latest template

Rejected. It makes existing Workspace objects change meaning without an explicit mutation and destroys reproducibility.

### Templates as mutable singleton objects

Rejected. Historical Runs and provenance need stable source versions.

### Duplicate/copy definitions without provenance

Rejected. It preserves edit independence but loses traceability, promotion lineage and the ability to explain where an object came from.

### Make Persona the persistence owner for all templates

Rejected. Workspace remains the product ownership root. Persona determines availability/surface context and may catalog templates without becoming a second root.

## Compliance

A template/object implementation complies when:

- instantiation copies a specific immutable template version;
- instantiated objects retain source template ID/version/hash;
- publishing a template update does not mutate existing objects;
- GraphTemplate dependencies are pinned or embedded;
- mutable execution identity/state is absent from template records;
- save-as-template/version creation is explicit and authorized;
- imported legacy definitions can identify their canonical projection and provenance;
- generated/improved definitions become explicit candidates/new versions rather than mutating historical records.

## References

- `ADR-081226-9944`: Canonical Product Hierarchy and Ownership
- `docs/analysis/ECOSYSTEM-INVENTORY.md`
- `docs/analysis/ARCHITECTURE-CONVERGENCE-MATRIX.md`
