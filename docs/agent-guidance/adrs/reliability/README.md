# Reliability ADRs

Progressive-disclosure index for ADRs governing retries, circuit breakers, fallbacks, health, SLO/error budgets, recovery behavior, and related resilience contracts.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-038: Reliability Taxonomy

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Build a current evidence/gap matrix across all five reliability primitives before any lifecycle promotion: retry policy and idempotency enforcement, per-dependency circuit breakers and probe ownership, explicit non-LLM fallbacks, SLO/error-budget calculation plus throttling, and liveness/readiness/startup semantics. Split remaining gaps into focused implementing specs/tests and transition ADR-038 only when the complete taxonomy is evidenced.  
**Current state:** Reliability implementation is materially underway: the ADR records recent circuit-breaker probe-lease semantics and maistro-server startup-health behavior, with health tests named in front matter. The decision is much broader than those implemented slices, and no complete current evidence record was located for retries, fallback coverage, SLO budget throttling, and all dependency breakers, so `Accepted` remains the honest status.  
**ADR:** [ADR-038: Reliability Taxonomy](../../../adr/ADR-038-reliability-taxonomy.md)
