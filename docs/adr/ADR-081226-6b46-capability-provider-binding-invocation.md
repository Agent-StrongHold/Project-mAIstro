---
id: ADR-081226-6b46
title: Capability, Provider, Binding and Invocation
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
  - maistro-engine#ADR-081226-a66b
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages/maistro-core/src/maistro/capabilities
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-081226-6b46: Capability, Provider, Binding and Invocation

- **Status:** Accepted
- **Date:** 2026-08-12
- **Deciders:** MAIstro maintainers
- **Technical Area:** Capabilities, tools, integrations, fulfillment

## Context

MAIstro currently fulfills work through capability providers, tool executors, HTTP clients, MCP tools, harness runners, sandbox backends, renderer/image providers, integrations and agent delegation. These systems overlap but represent different concerns: what can be done, which implementation can do it, what a consumer is allowed/configured to use, and one actual call.

## Decision

Canonical fulfillment is:

```text
Capability -> Provider -> Binding -> Invocation
```

### Capability

A Capability is a stable declared ability/contract. It describes semantics/schema, not authorization or a running process.

Examples include model inference, image generation, browser action, git operation, rendering, sandbox execution, external API operation and agent delegation.

### Provider

A Provider is an implementation candidate for a Capability. Provider owns implementation metadata, protocol support, health, availability and provider-level circuit/fallback signals.

Provider registration does not grant a Node permission to use it.

### Binding

A Binding is a consumer-specific configured and authorized route to a Capability. It may constrain/provider-pin:

- allowed Provider(s)
- protocol/endpoint configuration
- credential references
- scopes/options
- timeouts/limits
- tool exposure metadata
- policy/permission narrowing

Bindings are Workspace-scoped by default; Persona may control availability and Nodes reference permitted Bindings. Global/platform bindings require explicit scope/authorization.

Bindings MUST reference logical credentials, never copy secret values into Graph/Node definitions.

### Invocation

An Invocation is one actual fulfillment call. It records correlation to Workspace, Run, NodeRun, Attempt and Binding as applicable, the selected Provider, timing/outcome/usage/provenance and security/policy decisions needed for audit. Secret material is not persisted in Invocation payloads.

### Provider selection

Provider selection occurs at Invocation/admission time by default so current health/fallback policy can be considered. A Binding may pin one Provider or constrain the allowed set. Selection MUST remain inside the Binding's permission/configuration ceiling.

Fallback cannot widen authorization.

### Protocol

Protocol describes how fulfillment occurs, not a new executable object type. Canonical protocol families include function/tool, HTTP, MCP, harness/session, agent/A2A, human, sandbox/process and domain renderer/image protocols.

### Tool exposure

A Tool is primarily a model-facing exposure of an authorized Binding:

```text
Binding -> ToolExposure/schema -> model request -> Invocation
```

ToolExposure does not bypass Binding authorization and does not own execution lifecycle.

### Agents as capabilities/tools

An Agent/Graph may be exposed through an authorized Binding. Invoking an agent-backed Binding creates a child Run rather than an A2A-specific universal task lifecycle.

### Harnesses and sessionful providers

Harness/provider protocols may maintain external/session handles needed for fulfillment. Those handles are provider/binding/invocation state and do not replace canonical Run/NodeRun lifecycle.

### Credentials

Credentials are resolved just in time for an authorized Invocation. Binding stores references/requirements. Invocation receives only necessary resolved material and must not persist secret values.

### Resilience ownership

- Provider/Binding health and circuit state govern provider availability.
- Binding/Node policy governs semantic retry/fallback eligibility.
- ExecutionRuntime performs timing/cancellation mechanics.
- Invocation records each actual call/outcome.

## Consequences

- Tools, MCP, HTTP, harnesses, sandboxes and integrations converge without losing protocol-specific behavior.
- Provider fallback becomes health-aware without bypassing permissions.
- Agents-as-tools fit naturally through child Runs.
- Credentials have one resolution boundary.
- Existing capability registry can be retained where it maps cleanly, while tool registries become exposure/catalog layers rather than lifecycle owners.

## Compliance

A fulfillment path complies when an executable consumer reaches external/specialized behavior through an authorized Binding, Provider selection cannot exceed that Binding, one actual call is represented by Invocation, credentials are referenced/resolved rather than embedded, and protocol/tool layers do not create competing Run semantics.

## References

- `ADR-081226-9944`
- `ADR-081226-a66b`
- `docs/analysis/ARCHITECTURE-CONVERGENCE-MATRIX.md`
