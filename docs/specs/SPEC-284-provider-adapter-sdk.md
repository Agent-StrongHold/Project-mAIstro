---
id: SPEC-284
title: "Provider adapter SDK: one registration seam, one egress, declared secrets, shared conformance"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-10-06
accepted: 2026-10-06
implemented: 2026-10-06
history:
  - status: Proposed
    date: 2026-10-06
  - status: Accepted
    date: 2026-10-06
  - status: Implemented
    date: 2026-10-06
substrate:
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-082326-5386
  - maistro-engine#ADR-038
implements:
  - maistro-engine#ADR-105
related:
  - maistro-engine#ADR-101
  - maistro-engine#ADR-079
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/capabilities/test_provider_adapters.py
source:
  - packages/maistro-core/src/maistro/capabilities/provider_adapters.py
  - packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py
  - packages/maistro-core/src/maistro/container.py
  - packages/maistro-core/src/maistro/types/config.py
ac-modules:
  AC-1: maistro.capabilities.provider_adapters
  AC-2: maistro.capabilities.provider_adapters
  AC-3: maistro.capabilities.providers.llm_gateway
  AC-4: maistro.capabilities.providers.llm_gateway
  AC-5: maistro.capabilities.provider_adapters
  AC-6: maistro.capabilities.provider_adapters
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-284: Provider adapter SDK (M9-E1, #961)

## Context

ADR-105 decides that `maistro.capabilities.provider_adapters` is the whole
integration surface for an out-of-tree model provider: a declarative
`ProviderAdapterSpec` plus the `ProviderAdapter` normalization protocol,
registered through `register_adapter_models`, transported by the one approved
egress module, with credentials resolved by the canonical authority and
registration gated by `run_adapter_conformance`. This spec states the
measurable acceptance criteria and names the module each one asserts about.

## Decision

The six criteria below are the issue's acceptance list, restated as
per-criterion claims. Registration is the only seam (`create_container`
accepts a host-populated catalog through `provider_adapter_catalog`), the
spec carries no secret field, every wire crossing stays inside the gateway
module's inventoried POST, undeclared capabilities resolve as typed
unavailable before any HTTP, and the built-in reference adapter registers
through the identical conformance-gated seam as a third-party one.

## Acceptance criteria

- [x] **AC-1** An out-of-tree provider package registers models through
  `register_adapter_models` without editing core routing code, and the
  canonical `CostAwareRouter` selects adapter models under the same policy as
  built-in ones (duplicate ids, foreign objects under a registered id, and
  re-sourcing an existing model name are refused).
- [x] **AC-2** Secrets resolve through the canonical credential authority and
  never ride extension plaintext config: the spec refuses secret-shaped
  fields, bootstrap provisions the operator-supplied credential into the
  scoped pool under the declared reference, a foreign credential reference is
  refused, and an adapter hook never sees the secret.
- [x] **AC-3** Provider errors and usage map to canonical interfaces: the
  declared error taxonomy raises canonical `LlmAuthError`/`LlmHttpError` with
  real HTTP statuses, usage reported by the adapter hook reaches the canonical
  Invocation, and a taxonomy contradicting canonical resilience
  classification fails registration conformance.
- [x] **AC-4** A provider cannot bypass canonical routing, egress or security
  policy: adapter calls cross the same Binding/Invocation boundary through the
  approved gateway module, a foreign provider handle at that seam is a
  `TypeError` rather than an alternate egress, selection stays scoped to the
  Binding's declared adapter, and the operator-named endpoint origin joins the
  outbound policy exactly like `litellm_url` does.
- [x] **AC-5** Unsupported features fail explicitly: undeclared tools and
  undeclared structured output resolve as typed unavailable before any HTTP,
  and an unsupported protocol is refused at spec parse time.
- [x] **AC-6** The built-in reference adapter and a third-party-style adapter
  pass the same conformance suite where contracts overlap, and the suite
  catches lying adapters (usage understatement, taxonomy violations,
  secret-bearing specs, dropping normalizers, raising hooks).
