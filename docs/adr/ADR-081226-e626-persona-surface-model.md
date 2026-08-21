---
id: ADR-081226-e626
title: Persona and Product Surface Model
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-12
accepted: 2026-08-12
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
related:
  - maistro-engine#ADR-081226-9944
  - maistro-engine#ADR-081426-b1d3
  - maistro-engine#ADR-081226-6e34
---

# ADR-081226-e626: Persona and Product Surface Model

## Decision

A Workspace has exactly one live Persona. Persona exists to encode the Workspace's taste, style, and purpose so the same underlying MAIstro capabilities can behave like a coherent product rather than a generic bag of tools.

Persona is configuration and preference, not an actor, ACL, security boundary, or execution lifecycle.

Canonical Persona concerns include:

- identity/name and purpose,
- taste and aesthetic preferences,
- voice, tone, style, and theme,
- behavioral and creation defaults,
- default/preferred models and providers,
- preferred capabilities and Bindings,
- Workspace Template-catalog behavior,
- configured product surfaces such as UI, Builders CLI, and Builders RSI.

A Persona preference can influence selection only among options that are already legal and available in the current Project scope. Preferring a Provider, Binding, capability, or surface never creates authority to use it.

Persona MUST NOT contain a permission ceiling, grants, denies, credential visibility rules, Project memberships, or an independent security role hierarchy. Authorization belongs to Principal/WorkspaceMembership/Project scope/grants/denies/Policy.

## Agent distinction

Persona is not an Agent. An Agent is an execution actor represented through Graph/Node/Run semantics. Persona describes what the Workspace is for and how it tends to behave.

## Product surfaces

A Persona may configure which product surfaces are relevant or exposed for the Workspace experience. This is product configuration, not access control. Security checks remain authoritative if a configured surface attempts an operation.

## Consequences

Persona becomes simpler and more valuable: it can carry strong opinionated behavior without competing with Project authorization or Agent identity. Product UX can read Persona for defaults and presentation while security code can ignore Persona entirely.
