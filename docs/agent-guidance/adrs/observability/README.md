# Observability ADRs

Progressive-disclosure index for ADRs governing logs, metrics, traces, events, telemetry taxonomy, and related operational evidence.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-037: Observability Taxonomy

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Close SPEC-228's explicit ADR-037 gaps, either directly or by splitting AC-5 through AC-10 into focused child specs: canonical `maistro_*` metrics, required named spans, governed event topics, trace/agent log context, durable event retention, and explicit sampling/retention configuration. Transition ADR-037 only when the implementing specs/evidence satisfy the lifecycle requirements.  
**Current state:** Logging, metrics, tracing, and event-bus scaffolding exist, but SPEC-228 explicitly documents that ADR-037's canonical metric names, required spans, domain-event taxonomy, trace/agent log propagation, indefinite event persistence, and sampling/retention contract are not implemented. This is a genuine outstanding architecture gap, not stale status bookkeeping.  
**ADR:** [ADR-037: Observability Taxonomy](../../../adr/ADR-037-observability-taxonomy.md)
