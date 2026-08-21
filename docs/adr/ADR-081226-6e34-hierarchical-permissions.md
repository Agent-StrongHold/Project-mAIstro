---
id: ADR-081226-6e34
title: Scoped Grants and Deny-Wins Authorization
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
related:
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-9944
  - maistro-engine#ADR-081226-e626
---

# ADR-081226-6e34: Scoped Grants and Deny-Wins Authorization

## Decision

MAIstro authorization is modeled as scope plus authority/actions, not as one globally ordered role hierarchy.

WorkspaceMembership establishes access and broad Workspace grants. ProjectMembership and other scope-bound grants may add authority inside narrower scopes. Object-specific grants may add authority at still narrower scopes where supported.

For an object inside a Project tree, applicable grants accumulate from all scopes that contain the object:

```text
Workspace grants
+ Root Project grants
+ ancestor Project grants
+ target Project grants
+ object-specific grants
```

A grant never escapes the scope in which it was issued. A Project grant applies to that Project and descendants, not ancestors, siblings, or unrelated Projects. Because scope narrows independently from action strength, a principal may legitimately have stronger authority inside a narrower Project than elsewhere in the Workspace.

## Denies

Explicit denies accumulate across the same applicable scopes and always win over grants.

```text
effective authority = union(applicable grants) - union(applicable denies)
```

A descendant grant cannot grant around an inherited deny. The deny must be changed or removed at the scope where it originated.

Denies may target actions or resources, including capability, Binding, Credential, Provider, object type, or individual object identity where the authorization engine supports that selector.

## Delegation

Permission to perform an action does not imply permission to grant that action. Delegation/grant authority is explicit and remains scope-bound. A principal may only issue a grant when an applicable rule explicitly authorizes that delegation in the target scope.

## Resource visibility

Project resource visibility is a scope rule distinct from action grants. Project-scoped resources flow downward only. Authorization cannot make a child-scoped Credential or Binding visible to an ancestor or sibling unless an explicit resource-sharing primitive is introduced by a future ADR.

## Persona

Persona is not an authorization scope. Persona contributes no grants, denies, permission ceiling, credential visibility, or privilege. Persona preference resolution happens only after authorization/resource visibility establishes the legal candidate set.

## Policy

Policy may impose additional runtime/behavioral restrictions after structural grant/deny resolution. Policy MUST NOT silently turn a structural deny into an allow.

## Consequences

The old rule that every descendant can only narrow its parent is rejected as too simplistic. Narrow scopes can add authority, while deny-wins and scope containment prevent that authority from leaking outward.
