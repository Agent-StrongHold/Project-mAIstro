# Agent Architecture ADRs

Progressive-disclosure index for ADRs governing agent identity/specification, composition, recipes, selection, spawning, and related agent architecture.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-003: Agent runtime gap analysis (archived branch resolution)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the five original gap claims against their owning ADRs/specs as those records are audited; do not use the 2026-04-26 gap-status table as current implementation truth.  
**Current state:** ADR-003 is an accepted historical runtime-gap analysis and backlog mapping, not a current implementation inventory. Memory has materially advanced beyond the original "schema defined, not wired" state, while closure of identity, workspace context, scheduled autonomy, and runtime skill composability must be established from their owning architecture records and current implementations rather than inferred from this roadmap ADR.  
**ADR:** [ADR-003: Agent runtime gap analysis (archived branch resolution)](../../../adr/ADR-003-agent-runtime-gap-resolution.md)

## ADR-004: AgentSpec + AgentOutput envelopes

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Bring completion-duration evidence into compliance with the ADR: ensure a completed `AgentOutput` reliably records `duration_ms > 0`, strengthen the test from `>= 0` to `> 0`, verify the full ADR-004 acceptance set, then transition the ADR to `Implemented`.  
**Current state:** The typed agent request/response envelope is implemented and dedicated tests cover defaults, unique IDs, JSON round-trip, error recoverability, and completion timing. The implementation is not yet being promoted because the current timing test permits zero-duration completion while the accepted ADR requires a positive duration.  
**ADR:** [ADR-004: AgentSpec + AgentOutput envelopes](../../../adr/ADR-004-agent-spec.md)

## ADR-006: AgentRecipe + RecipeRegistry

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile this decision with ADR-081226-bb3a (Template, Object and Provenance Semantics). If that ADR is confirmed as the canonical successor for durable reusable definitions, add the explicit supersession relationship and transition ADR-006 to `Superseded`; retain RecipeRegistry only as the legacy compatibility/migration adapter required by the newer architecture.  
**Current state:** AgentRecipe and recipe loading still exist, but the accepted writable YAML RecipeRegistry contract is no longer the canonical durability model. Current code intentionally makes RecipeRegistry read-only for durable state and projects legacy recipes into canonical NodeTemplates with provenance, matching the newer template/object architecture. The ADR's recorded test path is also stale; current recipe tests live elsewhere and exercise the migration adapter.  
**ADR:** [ADR-006: AgentRecipe + RecipeRegistry](../../../adr/ADR-006-recipe-registry.md)

## ADR-009: Spawner pattern

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Determine the intended current authority of Spawner against the canonical Run/harness execution architecture. If Spawner remains canonical, prove production composition-root reachability and the full ADR-009 acceptance set; if it has become a compatibility/legacy execution path, identify the successor ADR, add the explicit supersession relationship, and retire or narrow Spawner accordingly.  
**Current state:** The Spawner implementation and dedicated tests still exist and implement the original single-agent execution funnel, including recipes, variants, typed parsing, error categorization, and upstream-output screening. Current repository search does not show Spawner construction in the production composition root, so implementation existence alone is insufficient to call ADR-009 Implemented or canonical; its reachability and authority must be reconciled with the newer durable Run/harness architecture.  
**ADR:** [ADR-009: Spawner pattern](../../../adr/ADR-009-spawner.md)

## ADR-060: Persona-as-seed — declarative domain templates, pluggable Scorer protocol, and two-tier eval statistics

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite/split this proposal before acceptance. Keep Persona as a declarative domain/product seed, but expand into the current canonical Persona/NodeTemplate/GraphTemplate/capability architecture rather than AgentRecipe. Separate the scorer/eval-statistics decision into focused ADR/spec ownership if needed so persona composition, evaluation providers, and preference-learning lifecycle do not become one oversized authority. Reconcile with the current Evolve/eval architecture and dependency policy.  
**Current state:** The proposal contains useful ideas, especially declarative persona/domain data and evidence-grounded evaluation, but its expansion path is anchored to the stale RecipeRegistry/Spawner model and it bundles several independently evolving architectural concerns. It remains Proposed, so it can be corrected directly without a supersession ceremony.  
**ADR:** [ADR-060: Persona-as-seed — declarative domain templates, pluggable Scorer protocol, and two-tier eval statistics](../../../adr/ADR-060-persona-as-seed-and-eval-protocol.md)

## ADR-094: Cut pydantic-ai from the conductor

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Verify pydantic-ai is absent from current dependency manifests/lock and that Conductor model calls now flow through the canonical governed model/harness egress rather than owning a raw bypass. Update the ADR so its direct-`httpx` LiteLLM call is historical implementation detail, then transition to `Implemented` if the "one agent runtime, no pydantic-ai" decision is fully evidenced or supersede it if a newer model-egress ADR owns the whole boundary.  
**Current state:** Repository search found no current pydantic-ai code references, so the removal objective appears substantially complete. The architecture has since moved beyond "Conductor calls LiteLLM directly" toward governed model/harness egress, making the dependency-removal decision still valid while its replacement-path description is stale.  
**ADR:** [ADR-094: Cut pydantic-ai from the conductor](../../../adr/ADR-094-cut-pydantic-ai-from-conductor.md)

## ADR-101: Foreign harness adapters, hierarchical orchestration, and agent/skill portability

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite before acceptance around the current "harness as capability/node" architecture. A foreign harness should be a Capability Provider selected by a Binding and executed as a canonical NodeRun/Attempt/Invocation inside a canonical Run; its process/session lifecycle is a provider effect, not a parallel execution lifecycle. Inbound foreign-orchestrator calls must admit canonical Runs rather than drive an untracked session side channel. Replace GraphRun/MasterOrchestrator assumptions, use ADR-093 sandbox floors, and make missing requested harness capability fail visibly unless an explicit fallback Binding exists rather than defaulting to silent `SAFE_NOOP`.  
**Current state:** The ADR's central insight remains highly valuable and matches current MAIstro direction: foreign harnesses such as Claude Code/Codex/Pi/OpenClaw can be treated as swappable execution providers under MAIstro's policy, sandbox, provenance, and portability controls. The 2026-06 proposal predates canonical Run/Invocation convergence, so its direct `harness_runner.send` and bidirectional session surfaces need to be remapped before acceptance.  
**ADR:** [ADR-101: Foreign harness adapters, hierarchical orchestration, and agent/skill portability](../../../adr/ADR-101-foreign-harness-adapters-and-portability.md)
