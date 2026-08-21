---
id: ADR-081426-b1d3
title: Project Scope Tree
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-14
accepted: 2026-08-14
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-14
  - status: Accepted
    date: 2026-08-14
related:
  - maistro-engine#ADR-081226-9944
  - maistro-engine#ADR-081226-6e34
  - maistro-engine#ADR-081226-e626
---

# ADR-081426-b1d3: Project Scope Tree

## Decision

A Project is the canonical nested organization, configuration, authorization, and resource-scope container inside a Workspace.

Every Workspace has exactly one persisted Root Project. The Root Project is created with the Workspace, has a stable identity, has no parent, cannot be moved or deleted, and is normally presented to users as the Workspace root rather than as a special folder. Every project-scoped durable object belongs to exactly one Project, including objects users create at the Workspace root.

Non-root Projects form an acyclic tree inside one Workspace. Projects never cross Workspace boundaries.

Templates are the deliberate exception to Project filing. NodeTemplate and GraphTemplate remain Workspace-wide reusable definitions. Instantiating a Template requires a destination Project; the resulting mutable object belongs to that Project while the Template remains Workspace-wide.

## Creation defaults

Project defaults are creation-time defaults, not live inheritance. Resolution proceeds from broadest to narrowest:

```text
Workspace defaults
-> Persona defaults
-> Root Project defaults
-> ancestor Project defaults
-> destination Project defaults
-> new object
```

Closest specified value wins. Once an object is created, it owns its resolved configuration. Later Project-default changes do not mutate it, and moving the object does not reapply defaults.

## Scoped resources

Credentials, Bindings, Capabilities, Integrations, Policies, and other explicitly scoped resources may be attached to a Project. Visibility flows downward through descendants only.

A resource attached to Project A is visible to A and descendants of A. It is not visible to A's parent, siblings, or unrelated Projects.

Moving an object to another Project is atomic. The move MUST be rejected if the destination scope cannot legally resolve resources the object already requires. A successful move changes scope and authorization immediately but does not rewrite the object's owned configuration.

## Project membership and authorization scope

WorkspaceMembership establishes access to the Workspace. ProjectMembership and scoped grants may add authority within a narrower Project subtree. Authority is not a single vertical role ranking.

Applicable grants accumulate over overlapping scopes. A grant never escapes the subtree in which it was issued. A narrower scope may grant stronger authority than the principal has elsewhere.

Explicit denies also accumulate, and denies win over grants. A descendant grant cannot bypass a deny inherited from an ancestor scope. Delegation is explicit: possessing an action such as `publish` does not imply authority to grant `publish` to someone else.

Persona is not part of this authorization chain. Persona encodes taste, style, purpose, and behavioral preferences; it cannot grant or deny access to Project resources.

## Deletion

Project deletion is fail-closed. A non-root Project cannot be deleted while it contains child Projects, project-scoped objects/resources, or memberships that require explicit disposition. There is no implicit recursive deletion, reparenting, or resource migration.

## Consequences

Project regains a legitimate canonical meaning without becoming an execution hierarchy or replacing Workspace. Existing Project code must be re-audited against this decision. Tree/resource behavior that matches this contract may be reused; old Project-as-Workspace ownership semantics and compatibility-only machinery remain deletion candidates.
