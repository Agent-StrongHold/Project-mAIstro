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

## ADR-056: Task crash recovery — durable resume with wave verification

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR for canonical recovery semantics across Run/NodeRun/Attempt, persisted Graph continuation, Invocation/effect claims for uncertain external side effects, durable approval/elevation state, and current usage/budget accounting. Reuse newer recovery ADRs such as ADR-082826-d9f5 where they already own a slice, but do not claim supersession until one decision covers ADR-056's full surviving recovery contract. Then supersede ADR-056.  
**Current state:** The requirement for crash-safe durable recovery remains critical, but ADR-056's mechanism is obsolete: TaskRecord checkpoint authority, shadow-git waves, Recipe/code-registry version replay, and the old ApprovalGate model have been replaced by canonical Run/NodeRun/Attempt and newer durable execution/effect machinery. Implementing this ADR literally would reintroduce competing execution state.  
**ADR:** [ADR-056: Task crash recovery — durable resume with wave verification](../../../adr/ADR-056-task-crash-recovery.md)

## ADR-063: Credential Pool and Automatic Key Rotation

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Remeasure all ADR-063 acceptance criteria against the post-#58 canonical Invocation integration, add direct request/outcome evidence for any criteria still only declared/passing, and update the historical body sections that describe the removed detached `execute_with_pool` retry loop. If selection/rotation/cooldown/blocking are all proven reachable through Provider resolution and Invocation outcomes, transition ADR-063 to `Implemented`.  
**Current state:** #58 materially converged this design: credential selection now flows through `maistro.container → effect_context → credential_routing → credentials.pool`, and rotation reacts to real Invocation outcomes rather than an invisible library retry loop. The credential modules left the unreachable baseline. The ADR remains Accepted pending a clean post-convergence AC/evidence reconciliation rather than relying on the old mechanism description.  
**ADR:** [ADR-063: Credential Pool and Automatic Key Rotation](../../../adr/ADR-063-credential-pool-and-rotation.md)

## ADR-066: P1 Resilience and Control

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Split/rewrite this proposal before acceptance so each concern lands at its current canonical boundary: delegation/subgraph depth on child Runs and delegation provenance; context compaction in the canonical context/harness path; steering as durable Run guidance/input; rate-limit coordination in provider/credential/quota routing; retry policy on Attempts/Invocations; model-context probing in provider/model capability resolution. Remove GraphRun-as-execution-owner and file-local coordination assumptions where they conflict with current architecture.  
**Current state:** The six operational concerns remain legitimate, but the proposal was built as an extension of ADR-062's now-retired GraphRun execution authority and bundles independently evolving subsystems into one decision. Keeping it Proposed is correct; accepting it unchanged would recreate non-canonical control and retry paths.  
**ADR:** [ADR-066: P1 Resilience and Control](../../../adr/ADR-066-p1-resilience-and-control.md)
