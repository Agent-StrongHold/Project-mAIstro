# Reliability ADRs

Progressive-disclosure index for ADRs governing retries, circuit breakers, fallbacks, health, SLO/error budgets, recovery behavior, and related resilience contracts.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-038: Reliability Taxonomy

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Build a current evidence/gap matrix across all five reliability primitives before any lifecycle promotion: retry policy and idempotency enforcement, per-dependency circuit breakers and probe ownership, explicit non-LLM fallbacks, SLO/error-budget calculation plus throttling, and liveness/readiness/startup semantics. Split remaining gaps into focused implementing specs/tests and transition ADR-038 only when the complete taxonomy is evidenced.  
**Current state:** Reliability implementation is materially underway: the ADR records recent circuit-breaker probe-lease semantics and maistro-server startup-health behavior, with health tests named in front matter. The decision is much broader than those implemented slices, and no complete current evidence record was located for retries, fallback coverage, SLO budget throttling, and all dependency breakers, so `Accepted` remains the honest status.  
**ADR:** [ADR-038: Reliability Taxonomy](../../../adr/ADR-038-reliability-taxonomy.md)

## ADR-054: Agent sandbox lifecycle and task budget enforcement

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR that restates sandbox isolation and hard resource-budget invariants on the current architecture: canonical Run/NodeRun/Attempt execution, Capability Binding/Invocation effects, current sandbox MCP/runtime, durable usage/quota accounting, and current approval/elevation semantics. Remove dependencies on AgentRecipe, shadow-git waves, and TaskRecord-as-budget-authority. Once accepted, supersede ADR-054.  
**Current state:** The safety goals remain relevant, but the concrete design is anchored to several stale/deprecated mechanisms: ADR-049 shadow git, ADR-052 waves, ADR-053 recipe overlays, ADR-051's old approval surface, and TaskRecord as durable execution/budget state. Implementing ADR-054 literally would recreate architecture the convergence effort is removing.  
**ADR:** [ADR-054: Agent sandbox lifecycle and task budget enforcement](../../../adr/ADR-054-sandbox-lifecycle-and-budgets.md)
