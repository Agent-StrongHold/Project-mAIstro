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

## ADR-085: Cost, Quota, and Rate Limiting

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a current spend-control ADR/spec that places accounting and enforcement on canonical Run/Attempt/Invocation and principal/Workspace scopes, then use it to supersede the stale Task-budget portions of ADR-054/085 as appropriate. Preserve nested limits, independent per-principal rate limiting, batch-vs-interactive cost classification, and attributable usage. Make ADR-068's rule explicit: over-budget is a hard veto cleared only by an explicit budget grant, never by generic elevation or RLPHD.  
**Current state:** The layered spend-control intent remains current, but the inner "per-task executor budget" boundary is obsolete and Router quota enforcement has explicitly been removed in favor of canonical Invocation enforcement. The ADR needs to converge with current usage/effect accounting rather than adding another quota path.  
**ADR:** [ADR-085: Cost, Quota, and Rate Limiting](../../../adr/ADR-085-cost-quota-rate-limiting.md)

## ADR-070426-ac56: Cross-model LLM fallback

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Reconcile this proposal with the fallback/retry mechanism that has since landed. The old target, Conductor's private retry loop, should not be extended; model/provider fallback belongs at canonical governed model egress/Invocation with registry health, credential routing, quota/rate-limit outcomes, and per-attempt evidence. If current implementation already satisfies that architecture, supersede this proposal with the newer provider-routing decision rather than implementing its Conductor DI plan.  
**Current state:** The failure mode identified here was real, but the repository has since added model fallback chains/retry and removed several private routing authorities. The ADR is now primarily historical rationale for cross-model fallback, not the implementation plan to follow.  
**ADR:** [ADR-070426-ac56: Cross-model LLM fallback](../../../adr/ADR-070426-ac56-cross-model-llm-fallback.md)

## ADR-081226-7248: Event and Checkpoint Model

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Continue converging GraphEvent, Builders events, collaboration streams, trigger/event buses, and recovery records onto the canonical durable Event envelope and immutable Checkpoint semantics. Close #1159-class follow-ups by routing oversized payloads to artifact references and applying secret/redaction policy before durable event persistence. Ensure state transition + event durability uses transaction/outbox/reconciliation rather than best effort.  
**Current state:** This is the canonical durable history/recovery model. Events are durable facts with Workspace-scoped sequencing and execution correlation; live buses are delivery projections. Checkpoints are resumability facts, not lifecycles, and resume creates a new Attempt. The September amendment also centrally bounds event payload/provenance size/depth.  
**ADR:** [ADR-081226-7248: Event and Checkpoint Model](../../../adr/ADR-081226-7248-event-checkpoint-model.md)

## ADR-081626-f383: Canonical Attempt execution lease and fencing

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep durable fencing as the authority for physical Attempt writers and compose it with the later lease-renewal/reclaim ADRs. Ensure every production Attempt mutation from a leased worker presents the current token and stale writers cannot terminalize or overwrite newer work. Remove unfenced production paths; retain unfenced construction only for explicitly low-level fixtures.  
**Current state:** This establishes the correct stale-worker primitive: monotonic lease epochs and opaque fencing tokens owned by the canonical Run store, consumed but not minted by ExecutionRuntime. Later August ADRs extend reclaim/renewal semantics rather than replacing this foundation.  
**ADR:** [ADR-081626-f383: Attempt execution lease and fencing](../../../adr/ADR-081626-f383-execution-lease-fencing.md)

## ADR-082426-19ed: Run success must be earned by NodeRuns

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep the store-level contradiction guard across every backend while ADR-082526-237d owns fuller terminal derivation. Re-executed nodes must be judged by their latest logical NodeRun, not permanently poisoned by an earlier failed occurrence.  
**Current state:** Direct spine-conformance tests protect against a Run claiming COMPLETED over a terminal failed/cancelled/timed-out latest NodeRun.  
**ADR:** [ADR-082426-19ed](../../../adr/ADR-082426-19ed-a-run-cannot-claim-success-over-a-failed-node.md)

## ADR-082426-e3ff: Fence every worker-authored write

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Enforce fencing not only on terminal writes but on acceptance/heartbeat/renewal and every other worker-authored mutation that could race with reclaim. Keep store-side rejection authoritative.  
**Current state:** This closes the loophole where a stale worker could still mutate authoritative Attempt state before final completion.  
**ADR:** [ADR-082426-e3ff](../../../adr/ADR-082426-e3ff-the-fence-guards-the-worker-authored-write.md)

## ADR-082526-b36a: Expired execution leases are reclaimed

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep liveness proof explicit through fenced renewal and compose reclaim with recovery disposition. Production executors must renew; reclaim only after lease expiry, cancel the abandoned Attempt with attributable cause, and let logical policy decide retry/resume.  
**Current state:** This completes the major liveness half left open by ADR-081626-f383: restart does not imply death, and a TTL without renewal is not sufficient.  
**ADR:** [ADR-082526-b36a](../../../adr/ADR-082526-b36a-a-lease-that-stops-being-renewed-is-reclaimed.md)

## ADR-082826-08f0: Interrupted-Run recovery disposition

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep one recovery table keyed to proven lease/liveness evidence and remove domain-specific restart/orphan rules. Recovery preserves Run/NodeRun identity and settles or creates Attempts through the canonical spine.  
**Current state:** This consolidates multiple contradictory recovery answers and is directly tested.  
**ADR:** [ADR-082826-08f0](../../../adr/ADR-082826-08f0-interrupted-run-recovery-disposition.md)

## ADR-082926-a6ab: Candidate validation stays inside candidate isolation

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Apply the isolation boundary to the entire RSI/evolve fitness path. Candidate tests, coverage, mutation/static tools, and candidate imports must run in the same or stronger isolated environment as the edits, aligned with ADR-093.  
**Current state:** This fixes a real boundary mismatch in isolated RSI validation.  
**ADR:** [ADR-082926-a6ab](../../../adr/ADR-082926-a6ab-candidate-validation-runs-where-the-edits-do.md)

## ADR-083026-14c3: Repair emptied Attempt output only with proof

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Repair only canonical RunStore rows where a second authoritative copy proves output was lost. Never infer missing content or inspect a legacy store as if it were authoritative.  
**Current state:** This records withdrawal of an unsafe repair that inspected the wrong persistence owner.  
**ADR:** [ADR-083026-14c3](../../../adr/ADR-083026-14c3-repairing-an-emptied-attempt-output.md)
