---
id: ADR-105
title: "Third-party provider adapter SDK: registration seams, canonical-only egress, shared conformance"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-05
accepted: 2026-10-05
substrate:
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-082326-5386
  - maistro-engine#ADR-038
implements: []
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
ac-modules:
  AC-1: maistro.capabilities.provider_adapters.register_adapter_models
  AC-2: maistro.capabilities.provider_adapters.bootstrap_provider_adapters
  AC-3: maistro.capabilities.providers.llm_gateway.execute_model_chat
  AC-4: maistro.capabilities.provider_adapters.run_adapter_conformance
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Accepted
    date: 2026-10-05
---

# ADR-105: Third-party provider adapter SDK (M9-E1, #961)

- **Status:** Accepted
- **Date:** 2026-10-05
- **Deciders:** MAIstro maintainers
- **Technical Area:** Capabilities, model providers, extension surface

## Context

Epic M9-E (#942) wants external developers adding model providers without core
edits while every authority, network access and Invocation stays canonical.
The engine already has the canonical effect path (Capability → Provider →
Binding → Invocation, ADR-081226-6b46), one approved model-egress Provider
(#56: the OpenAI-compatible gateway protocol in
`maistro.capabilities.providers.llm_gateway`), the ADR-079 registry/router
pair, scoped credential pools (#58/#1091), and a frozen direct-model-egress
inventory (#36/#542): the set of modules holding model HTTP may only shrink.
What was missing is a published contract that lets an out-of-tree package join
that machinery — declaring its models, capabilities, auth requirements, error
taxonomy and health signals — without becoming a second transport, a second
secret store, or a second routing authority.

## Decision

`maistro.capabilities.provider_adapters` is the provider-adapter SDK. An
out-of-tree package implements the `ProviderAdapter` normalization protocol
over a declarative `ProviderAdapterSpec` and calls `register_adapter_models` —
that is the whole integration. Four rules hold the line:

1. **One registration seam, canonical routing unchanged.** Registration maps
   declared models 1:1 into the ADR-079 registry (cost/latency/fallback
   metadata included), so `CostAwareRouter` selects adapter models under the
   same policy as built-in ones. Nothing in `maistro.providers` or
   `maistro.router` changes per provider; a model name with an existing owner
   is refused rather than re-sourced.
2. **One egress.** Adapters do not hold HTTP clients. The approved gateway
   module transports them over the same single chat-completions POST it already
   owned: an adapter contributes its normalized payload, its declared
   credential presentation (bearer/header/query), its timeout, and its error
   taxonomy — the boundary, the Invocation, the quota door and the resilience
   classifier are untouched. A foreign provider handle at that seam is a
   `TypeError`, not an alternate egress.
3. **Secrets by declaration, values by authority.** The spec has no secret
   field (`extra="forbid"` refuses one at parse time; the conformance suite
   re-asserts it on the instance). The physical credential is provisioned by
   operator deployment configuration (never adapter-package configuration)
   into the scoped credential router, resolved per call by credential routing,
   and injected by the transport per the adapter's declared auth style. An
   adapter hook never sees a secret.
4. **Explicit capability failure, shared conformance.** Capabilities default
   to undeclared; a tools/structured-output request against an undeclared
   capability resolves as typed unavailable before any HTTP. Registration runs
   `run_adapter_conformance` — declaration honesty, normalization shapes for
   *every* declared model under the transport's strict JSON encoder, usage
   reporting, the pinned error taxonomy (auth statuses → auth, 429 →
   rate-limited, 5xx → retryable, every other 4xx → permanent — always
   agreeing with canonical classification), health normalization,
   no-secret-surface — and refuses a nonconforming adapter before any model
   enters routing. The built-in `ReferenceChatAdapter` registers through the
   identical seam, so built-in and external providers pass the same suite
   where contracts overlap.

Operator wiring mirrors model-binding bootstrap: `bootstrap_provider_adapters`
reads `AgentConfig.provider_adapters`, self-registers the built-in reference
adapter on demand (at the deployment's configured `litellm_url`, with the
Compose-internal hostname as the default), requires every other id to be
pre-registered by the host — `create_container` accepts the host's
pre-populated catalog through `provider_adapter_catalog`, the seam an
out-of-tree package's registration flows through — provisions credentials
into the scoped pool, seeds the operator-named endpoint origin into the
outbound policy (additive, exactly like `litellm_url`), and loads one
`model.chat` Binding per entry carrying the entry's `node_id`/`policy_refs`
scoping exactly as `ModelBindingConfig` does. Boot-time health probing is per
entry: `probe_health_at_boot` on one entry probes that adapter only, never
the other registered adapters. A registered adapter authorizes nothing by
itself. Adapter health probes (unauthenticated by declaration) are recorded
on the catalog and read inside canonical provider resolution, so an adapter
that failed its probe resolves as unavailable until recovery — provider-level
signal, canonical refusal, no second circuit breaker.

The error taxonomy is pinned to canonical classification: every status the
resilience classifier reads (4xx auth/permanent, 429 rate-limited, 5xx
retryable) must map to the kind the classifier will infer from that status,
so an adapter can classify within the taxonomy but never contradict
canonical retry/cooldown policy — a declaration that would flip "HTTP 500 is
permanent" fails registration conformance. Pre-effect adapter code (request
normalization) that refuses a runtime input raises `EffectNotApplied` — no
external effect occurred — instead of leaving the Invocation UNKNOWN. The
spec's `base_url` is validated as a real absolute http(s) URL with a host and
refused if it carries userinfo: credential material never rides the spec.

The SDK module sits on the promotion-path import closure and is classified
on the containment surface (`maistro_rsi/sensitive_paths.py`): it decides
what future model calls may reach, so its diffs escalate to adversarial
review rather than riding a tolerance.

## Consequences

- An out-of-tree provider package needs no core edit and no fork of routing,
  egress, secrets, or recording to serve models.
- The wire protocol an adapter can join is the canonical OpenAI-compatible
  chat-completions shape; a provider that cannot speak it fails registration
  explicitly instead of dragging in a transport.
- Streaming stays declaration-only in this slice: physical egress remains one
  non-stream call (the canonical stream contract yields the single normalized
  body), and a streaming wire is future work against the same boundary.
- The direct-model-egress inventory does not grow: the adapter path reuses the
  one inventoried POST.

## Compliance

A deployment complies when every adapter model is selected by the canonical
router, authorized by a Binding, transported by the approved gateway module,
recorded as an Invocation, quota-charged, and resilience-classified — and
when a refused adapter (conformance, duplicate, re-source, undeclared
capability, failed health probe) fails loudly instead of degrading.

## References

- ADR-079 (model registry/routing; Proposed — historical companion, listed
  under `related`), ADR-081226-6b46 (canonical effect path),
  ADR-082326-5386 (outbound HTTP policy seam), ADR-038 (fallback/circuits)
- Issue #961 (M9-E1), Epic #942 (M9-E)
