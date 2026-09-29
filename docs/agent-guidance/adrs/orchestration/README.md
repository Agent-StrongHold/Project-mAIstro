# Orchestration ADRs

Progressive-disclosure index for ADRs governing scheduling, selection, orchestration, execution coordination, and related runtime control behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-007: VariantSelector (Thompson sampling)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Add acceptance-strength tests that exercise the real seeded Thompson-sampling path and demonstrate that a strongly successful variant is favored after sufficient outcomes without replacing `random.betavariate` with a deterministic stub. Verify deterministic behavior under `random.seed()`, run the focused suite, then transition ADR-007 to `Implemented` if the full acceptance set passes.  
**Current state:** VariantSelector is implemented with round-robin warm-up, exploration, Beta-distribution Thompson sampling, outcome bookkeeping, and optional Langfuse-backed statistics. Current tests strongly cover control flow and bookkeeping, but they mock the sampler for winner selection and therefore do not yet prove the ADR's actual statistical-favoring and seedability criteria.  
**ADR:** [ADR-007: VariantSelector (Thompson sampling)](../../../adr/ADR-007-variant-selector.md)

## ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether reserved-capacity LIVE/BACKGROUND scheduling remains a requirement under the canonical durable Run/worker architecture. If it remains required, replace the obsolete TaskRunner-slot design with a current spec and implementation that preserves the latency-isolation invariant; if it is no longer desired, create or identify the withdrawing/successor ADR and transition ADR-010 accordingly.  
**Current state:** The accepted ADR describes a TaskRunner split into reserved live/background worker slots, but repository search finds no implementation of those slots and SPEC-211 still has the corresponding criteria unchecked. Newer campaign/priority architecture does not supersede this decision because it explicitly does not add a scheduler, so ADR-010 is currently an accepted but apparently unimplemented scheduling requirement tied to an obsolete execution shape.  
**ADR:** [ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)](../../../adr/ADR-010-lane-scheduling.md)

## ADR-046: Scheduler — Recurring agent tasks

**Status:** Superseded  
**Last updated:** 2026-09-28  
**Next steps:** None. Follow ADR-082126-f69c: recurrence produces canonical Runs rather than owning a second scheduler execution lifecycle.  
**Current state:** ADR-046 is explicitly superseded and records that its APScheduler/TaskRecord-centered mechanism was never the canonical implementation. Its durable/timezone/max-runs requirements informed the successor, but its execution mechanism must not be revived. Note that ADR-044's historical reference to a future "ADR-046" for Canvas legacy deletion is stale because this ID belongs to Scheduler.  
**ADR:** [ADR-046: Scheduler — Recurring agent tasks](../../../adr/ADR-046-scheduler.md)

## ADR-052: Parallel agent waves — per-wave branch isolation and fan-in merge

**Status:** Deprecated  
**Last updated:** 2026-09-28  
**Next steps:** No implementation work against ADR-052. Remove its unreachable fan-in/shadow-git island during convergence cleanup. Any current parallel-agent execution must be designed on the canonical Graph/Run/workspace architecture rather than reconnecting this deprecated lifecycle.  
**Current state:** Reachability analysis proved the implementation was never connected, and the design depends on deprecated ADR-049 shadow-git machinery. It was correctly moved from an implementation claim to Deprecated with no successor; ADR-062 addresses a different traversal concern and does not revive this filesystem-wave model.  
**ADR:** [ADR-052: Parallel agent waves — per-wave branch isolation and fan-in merge](../../../adr/ADR-052-parallel-agent-waves.md)

## ADR-053: Recipe overlay composition — engine simple + product overlay

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR that carries the useful composition rules into the current Persona/Template/Capability-Binding architecture: deterministic schema-driven overrides, explicit versioned code references where still applicable, and non-overridable security-sensitive fields. Do not preserve RecipeRegistry compatibility as a goal. Once the successor is accepted, transition ADR-053 to `Superseded`.  
**Current state:** ADR-053 is built on the stale ADR-006 RecipeRegistry and ADR-035 catalog model, and one acceptance criterion explicitly requires backward compatibility with ADR-006. That conflicts with both current architecture and the pre-1.0 rule that compatibility has no positive design weight. The composition/governance idea remains useful, but the owning abstraction must change.  
**ADR:** [ADR-053: Recipe overlay composition — engine simple + product overlay](../../../adr/ADR-053-recipe-overlay-composition.md)

## ADR-058: Agent-to-agent (A2A) delegation protocol — in-process and federated

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite this proposal against the canonical execution architecture before acceptance. Delegation should create/relate canonical child Runs with durable principal/delegation provenance, authorization/Capability Binding, Run/NodeRun/Attempt ownership, continuation/recovery semantics, and governed remote effects; local vs federated should be transport differences, not separate execution lifecycles. Reconcile the rewrite with the current remote-delegation/continuation M1 work and remove stale DID-required, WorkerPool, in-memory-task, and legacy AgentCard assumptions.  
**Current state:** The original proposal accurately identified dead A2A scaffolding, loop/budget guards, SSRF risk, and the need for one delegation concept, but its proposed A2ABroker/transport lifecycle predates canonical child Runs and the durable delegation work now in the repo. Current remote delegation already participates in canonical Run/continuation machinery, making this Proposed ADR directly relevant to M1 but unsafe to accept as written.  
**ADR:** [ADR-058: Agent-to-agent (A2A) delegation protocol — in-process and federated](../../../adr/ADR-058-a2a-delegation-protocol.md)

## ADR-062: Graph Execution Protocol

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **M1-critical:** establish the explicit successor for canonical Graph execution and supersede ADR-062. Its own current text says the `run_graph` execution entry point was retired by #1154 and canonical durable execution is `maistro.graph.durable_runs`, sharing no code with GraphRun. If the newer Run/NodeRun/Attempt + durable Graph projection ADR family does not provide one complete successor, create a convergence ADR that does, then transition ADR-062 to `Superseded`. Retain GraphRun only as non-authoritative domain/test traversal if still useful.  
**Current state:** The central architectural decision ADR-062 originally made, GraphRun/NodeRun as execution authority behind `run_graph`, is no longer live. The old entry point was deliberately removed because it produced physical work without canonical Run/NodeRun/Attempt evidence or restart recovery. Leaving this record Accepted without an explicit successor is misleading for agents and directly conflicts with M1's single-execution-authority goal.  
**ADR:** [ADR-062: Graph Execution Protocol](../../../adr/ADR-062-graph-execution-protocol.md)

## ADR-062: Graph Execution Protocol

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create/identify a successor ADR that formally separates Graph-domain traversal/NodeStrategy semantics from canonical execution authority, then supersede ADR-062. The successor must state that physical execution and recovery are owned exclusively by canonical Run/NodeRun/Attempt plus `maistro.graph.durable_runs`; `GraphRun`/legacy `NodeRun` may remain only as non-authoritative domain/test-harness structures where still useful.  
**Current state:** ADR-062's own amendment records that its `run_graph` execution path was retired by #1154 because it emitted no canonical Run/NodeRun/Attempt evidence and was unrecoverable after restart. Canonical durable Graph execution now shares no code with this design. The remaining strategy/traversal concepts may still be useful, but leaving the ADR simply Accepted risks teaching agents that `GraphRun` is an execution owner, directly conflicting with M1 convergence.  
**ADR:** [ADR-062: Graph Execution Protocol](../../../adr/ADR-062-graph-execution-protocol.md)

## ADR-071: General Task Planner & Orchestration

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite this proposal around canonical GraphTemplate/NodeTemplate planning, Run/NodeRun/Attempt execution, child-Run delegation, durable continuations/recovery, current scheduler/priority semantics, Capability Invocation effects, Workspaces, and ADR-068 authorization. Preserve useful planner ideas such as reuse-first planning, explicit success conditions, interpretable search/scoring, replanning on drift, deadlines, and verification, but remove dependencies on deprecated shadow-git waves and retired GraphRun/TaskRecord execution. Reassess speculative execution under real effect/idempotency guarantees rather than "rollback is cheap."  
**Current state:** The orchestration problem is real, but the Proposed design is a synthesis of several mechanisms that convergence has since retired or relocated. Accepting it unchanged would recreate competing execution, recovery, budget, and filesystem-wave authorities. Its planner/reconciler concepts should be retained only after remapping them onto the canonical execution spine.  
**ADR:** [ADR-071: General Task Planner & Orchestration](../../../adr/ADR-071-task-planner-orchestration.md)

## ADR-079: LLM Provider / Model Registry, Routing, and Embeddings

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite this proposal to describe the model architecture that now exists: canonical governed model/harness egress, Provider/Model registry and capability metadata, Provider resolution through canonical Invocation, credential/quota/health-aware routing, explicit retry/fallback chains, and local always-available providers such as the non-latency-sensitive Qwen path. Split embeddings into a separate ADR/spec because embedding generation/versioning/re-embed lifecycle is a memory/vector concern with different storage and scheduling semantics. Reconcile runtime-editable routing with ADR-078 only after ConfigStore is real.  
**Current state:** The Proposed ADR predates major model-routing convergence and bundles model selection with embeddings. Current provider/credential/fallback architecture has already moved beyond its simple `Router.pick()/fallback_chain()` sketch. Because it remains Proposed, the right move is to rewrite it to document the actual canonical path rather than implement the obsolete design.  
**ADR:** [ADR-079: LLM Provider / Model Registry, Routing, and Embeddings](../../../adr/ADR-079-model-registry-routing-embeddings.md)

## ADR-086: Events, Triggers, and the Reactor

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite before acceptance around the current durable event/trigger architecture: durable event log, declarative trigger matching, occurrence claim via canonical InvocationStore, and resulting canonical Run/Invocation admission rather than Recipe/Task execution. Preserve the September 2026 leased/fenced ConsumerCursor semantics, monotonic advance, settle-before-persist, and gap handling. Reconcile this trigger/event stream with ADR-037's separate domain-event taxonomy so agents do not conflate the two buses.  
**Current state:** The proposal contains newer, concrete durability work that has landed, especially fenced consumer cursors and idempotent occurrence claims, but its original execution target still says triggers fire recipes and scheduled tasks inherit ADR-046, which is superseded. Because ADR-086 remains Proposed, its body should be updated to the architecture that now exists before acceptance.  
**ADR:** [ADR-086: Events, Triggers, and the Reactor](../../../adr/ADR-086-events-triggers-reactor.md)

## ADR-089: Intent Classifier — thresholded escalation and multi-intent routing

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Audit whether IntentClassifier remains a canonical reachable pre-admission/routing component. If retained, remap its outputs to current GraphTemplate/NodeTemplate selection, Provider/model routing, and canonical child-Run decomposition for multi-intent requests; remove ADR-010 lane/Task-era assumptions and only source thresholds from ADR-078 once ConfigStore is implemented. If the current harness/planner architecture makes a separate intent classifier redundant, create a successor/supersession decision rather than maintaining another routing authority.  
**Current state:** The cheap deterministic → model-on-ambiguity pattern is sensible, but the ADR's downstream consumers and multi-intent execution model predate current canonical execution. This audit did not establish production reachability, so the decision remains Accepted pending an authority/reachability check.  
**ADR:** [ADR-089: Intent Classifier — thresholded escalation and multi-intent routing](../../../adr/ADR-089-intent-classifier.md)

## ADR-070426-b5e9: Six-tier priority system (P0-P5)

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Decide whether one six-tier label still usefully spans scheduling, routing, spend, and observability after TaskQueue/TaskRunner retirement. If retained, attach it to canonical Run admission/scheduling and treat model/token/cost behavior as policy mappings rather than immutable tier semantics. Remove Builders-specific P4/P5 meanings and all legacy compatibility defaults.  
**Current state:** A shared priority label can prevent cross-subsystem disagreement, but this proposal hard-codes workload meanings and resource multipliers around obsolete Task/Builders architecture. Priority should describe urgency/service class, not permanently encode which historical subsystem created the work.  
**ADR:** [ADR-070426-b5e9: Six-tier priority system](../../../adr/ADR-070426-b5e9-six-tier-priority-system.md)

## ADR-081226-69ee: Graph and Node Execution Model

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Treat this as canonical and finish deleting/migrating every competing GraphRun/GraphConfig/Builders/Task execution owner identified by the convergence ledgers. Preserve domain traversal behavior through parity tests while all physical execution flows through Run/NodeRun/Attempt + ExecutionRuntime. Child graph work creates child Runs and remains inside one Workspace unless a separately authorized destination Project is selected.  
**Current state:** This is the current Graph architecture: Graph is the editable composition, Node is the executable position, Run captures an immutable scoped Graph snapshot, GraphExecutionState owns traversal only, and duplicate graph lifecycle records are explicit migration/deletion targets. Older ADR-062/065/071/090/099 must be read through this decision.  
**ADR:** [ADR-081226-69ee: Graph and Node Execution Model](../../../adr/ADR-081226-69ee-graph-node-execution-model.md)

## ADR-081226-a66b: Run, NodeRun and Attempt Lifecycle

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Continue M1 until every admitted execution uses this one lifecycle and all competing universal state machines are retired or reduced to domain projections. Keep recovery/retry as new Attempts under the same logical NodeRun where appropriate; ensure terminalization, cancellation, timeout classification, parent/child correlation, and scope invariants are mechanically enforced by stores/runtime.  
**Current state:** This is MAIstro's canonical execution spine and the principal convergence target for the repository. Run owns logical execution, NodeRun owns one logical node occurrence, Attempt owns one physical try, and ExecutionRuntime owns mechanics only. Queue, schedule, delegation, harness, Builders, and persistence projections explicitly do not own competing post-admission lifecycles.  
**ADR:** [ADR-081226-a66b: Run, NodeRun and Attempt Lifecycle](../../../adr/ADR-081226-a66b-run-noderun-attempt-lifecycle.md)
