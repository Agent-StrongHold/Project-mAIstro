---
id: ADR-081226-9944
title: Canonical Product Hierarchy and Ownership
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-e626
  - maistro-engine#ADR-081226-a66b
---

# ADR-081226-9944: Canonical Product Hierarchy and Ownership

## Decision

Workspace is MAIstro's durable environment boundary. It is not owned structurally by one User; Users relate to Workspaces through WorkspaceMembership so personal and shared Workspaces use the same ownership model.

Every Workspace has exactly one live Persona, a Workspace-wide Template catalog, and exactly one implicit persisted Root Project.

```text
Principal / User
    ↓
WorkspaceMembership
Workspace
├── Persona
├── Templates[]
└── Root Project
    ├── Project[]
    ├── Graph[]
    ├── Run[]
    ├── Session[]
    ├── Artifact[]
    ├── Memory
    ├── Schedule[]
    ├── Credential[]
    ├── Integration[]
    └── Policy[]
```

Project is not an obsolete synonym for Workspace. Project is the nested organization, configuration, authorization, and resource-scope container inside a Workspace. The dedicated Project decision is governed by `ADR-081426-b1d3`.

Templates are Workspace-wide reusable definitions. Project-scoped mutable objects are filed in exactly one Project. Instantiating a Template into a mutable object requires a destination Project.

## Product versus execution concepts

Persona configures the Workspace's taste, style, purpose, and behavioral preferences. Persona is not an execution actor and is not an authorization principal.

Graph is the editable composition object. Node is its executable position.

Run is the universal logical execution record. NodeRun is one logical execution of a Node within a Run. Attempt is one physical try. ExecutionRuntime owns physical execution mechanics only.

```text
Graph -> Node[]
Run -> NodeRun[] -> Attempt[] -> ExecutionRuntime
```

Capability fulfillment is orthogonal to ownership and lifecycle:

```text
Capability -> Provider -> Binding -> Invocation
```

## Ownership invariants

- Every durable product object MUST identify its Workspace.
- Every project-scoped durable object MUST additionally identify exactly one Project in that Workspace.
- Templates are the intentional Workspace-wide exception to Project filing.
- A Run and its captured Graph snapshot MUST preserve both Workspace and Project identity.
- Sessions remain distinct from Runs and may span Runs.
- Child Runs may explicitly cross Project boundaries inside one Workspace when authorized, but ordinary child Run creation never crosses Workspace boundaries.

## Migration posture

MAIstro does not preserve obsolete interfaces solely for compatibility. Migration is:

```text
build canonical model
-> move useful behavior
-> change real callers
-> delete obsolete system
```

Existing behavior worth preserving receives parity tests. Replaced architecture does not receive a permanent compatibility facade.
