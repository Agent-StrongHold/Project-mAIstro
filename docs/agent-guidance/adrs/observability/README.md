# Observability ADRs

Progressive-disclosure index for ADRs governing logs, metrics, traces, events, telemetry taxonomy, and related operational evidence.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-037: Observability Taxonomy

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Close SPEC-228's explicit ADR-037 gaps, either directly or by splitting AC-5 through AC-10 into focused child specs: canonical `maistro_*` metrics, required named spans, governed event topics, trace/agent log context, durable event retention, and explicit sampling/retention configuration. Transition ADR-037 only when the implementing specs/evidence satisfy the lifecycle requirements.  
**Current state:** Logging, metrics, tracing, and event-bus scaffolding exist, but SPEC-228 explicitly documents that ADR-037's canonical metric names, required spans, domain-event taxonomy, trace/agent log propagation, indefinite event persistence, and sampling/retention contract are not implemented. This is a genuine outstanding architecture gap, not stale status bookkeeping.  
**ADR:** [ADR-037: Observability Taxonomy](../../../adr/ADR-037-observability-taxonomy.md)

## ADR-055: Observability extensions — recorded-response replay and PII sensitivity tiers

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite this proposal against current architecture before acceptance: governed model/harness egress for LLM evidence, Capability Invocation for tool-call evidence, canonical Run provenance, current audit/event persistence, and current security/sensitivity policy. Remove dependencies on deprecated waves/shadow-git and stale ToolRegistration/RecipeOverlay abstractions. Then define how replay evidence and normal/sensitive/secret handling compose with ADR-037's still-open observability gaps.  
**Current state:** The underlying goals, replayable external-call evidence and sensitivity-aware retention/redaction, remain potentially valuable. The proposed interception points and several dependencies predate the canonical Run/harness/Capability Invocation architecture, while ADR-037 itself is not yet fully implemented. Keeping this ADR Proposed prevents stale mechanisms from becoming an accidental mandate.  
**ADR:** [ADR-055: Observability extensions — recorded-response replay and PII sensitivity tiers](../../../adr/ADR-055-observability-replay-and-pii-tiers.md)

## ADR-082: Alerting, SLO, and Trace Context Propagation

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR and then supersede ADR-082. Preserve SLO/error-budget-driven alert events, channel-agnostic notification intent, and end-to-end correlation, but replace the deprecated ADR-047 delivery gateway and ADR-052 waves with current notification/capability architecture and canonical Run/NodeRun/Attempt/Invocation/delegation provenance. Define trace persistence only after ADR-037's canonical observability substrate is closed.  
**Current state:** The ADR's alert path depends on ADR-047, which is explicitly Deprecated because its implementation was unreachable, and its trace topology names deprecated parallel waves. The operational goals remain useful, but the mechanism is no longer viable. Implementing ADR-082 literally would reconnect dead subsystems.  
**ADR:** [ADR-082: Alerting, SLO, and Trace Context Propagation](../../../adr/ADR-082-alerting-and-tracing.md)

## ADR-083026-12f7: Run records declare what they report

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep persisted/history projections explicit: no dynamic fields, undocumented retention, or UI durability claims beyond the real bound. Prefer projections over canonical Runs rather than product-owned run lifecycles.  
**Current state:** This fixes volatile Conductor run-history state that reported undeclared fields and implied persistence it did not have.  
**ADR:** [ADR-083026-12f7](../../../adr/ADR-083026-12f7-a-run-record-declares-what-it-reports.md)

## ADR-083026-1cb1: One ambient execution correlation context

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Bind the same context at every seam carrying Workspace/Project/Run/NodeRun/Attempt/Invocation/Session identity, including non-HTTP work. Logs, traces, and events should read these ambient IDs rather than invent parallel correlation plumbing.  
**Current state:** This supplies the propagation mechanism beneath the canonical Event/correlation model.  
**ADR:** [ADR-083026-1cb1](../../../adr/ADR-083026-1cb1-one-execution-correlation-context.md)

## ADR-083026-a91e: Unmeasured metric is absent, not zero

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep telemetry fields optional/unknown until actually measured. Optimizers and dashboards must exclude or explicitly model missing observations rather than ranking fabricated zeros.  
**Current state:** This prevents unknown cost/latency/token data from masquerading as perfect performance.  
**ADR:** [ADR-083026-a91e](../../../adr/ADR-083026-a91e-an-unmeasured-metric-is-absent-not-zero.md)

## ADR-083026-aba1: No caller and no measurement are both stated

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Update this record's historical "Invocation has no production caller" statement against the September capability/credential-routing work. Preserve its core rule: records explicitly state whether a caller/measurement exists, and token/cost totals report coverage rather than silently treating missing provider usage as zero.  
**Current state:** On August 30 this correctly exposed Invocation as implemented-but-unreached. Subsequent work has begun moving real provider behavior into the canonical Invocation/effect seam, so the reachability claim must now be remeasured rather than repeated.  
**ADR:** [ADR-083026-aba1](../../../adr/ADR-083026-aba1-no-caller-and-no-measurement-are-both-stated.md)
