# Canonical August Architecture Specs

These specs are the primary implementation/evidence map for current MAIstro architecture. Older Task/Recipe/GraphRun/Hive-owned execution specs must be interpreted through these contracts.

## SPEC-072726-3439: Installer end-to-end flow
**Status:** Proposed  
**Next steps:** Reconcile first-run identity/setup questions with current canonical principal/Workspace ownership and verify curl/iex → stack health → setup → first model call → tutorial. Optional crypto identity must remain optional.  
**Current state:** Much of the installer skeleton exists; the end-to-end product journey is not yet proven.  
**SPEC:** [SPEC-072726-3439](../../../specs/SPEC-072726-3439-installer-e2e-flow.md)

## SPEC-080126-3a7c: Durable scheduler
**Status:** Superseded  
**Next steps:** None. Follow ADR-082126-f69c and current recurrence/consumer specs.  
**Current state:** Correctly superseded when recurrence was redefined to admit canonical Runs rather than own execution.  
**SPEC:** [SPEC-080126-3a7c](../../../specs/SPEC-080126-3a7c-durable-scheduler.md)

## SPEC-080126-9e42: Memory decay driver
**Status:** Accepted  
**Next steps:** Re-evidence that periodic decay is production-reachable through current recurrence→Run→consumer execution and operates on the durable episodic store.  
**Current state:** Implementation history exists; M0 rolled it back because pure decay correctness did not prove runtime reachability.  
**SPEC:** [SPEC-080126-9e42](../../../specs/SPEC-080126-9e42-memory-decay-driver.md)

## SPEC-080226-4c1f: Log redaction wiring
**Status:** Accepted  
**Next steps:** Re-evidence all canonical logging/error/event/trajectory surfaces, including server and non-HTTP workers, against the central redactor. Promote only when no production path emits unredacted secrets.  
**Current state:** This is the integration half missing from SPEC-223; M0 rollback requires current reachability evidence.  
**SPEC:** [SPEC-080226-4c1f](../../../specs/SPEC-080226-4c1f-log-redaction-wiring.md)

## SPEC-080226-510f: Content-addressed approval rules
**Status:** Proposed  
**Next steps:** Redesign standing approvals on canonical Binding/Invocation plus current durable approval/crypto-bound evidence. Bind rules to exact capability/provider/tool identity and normalized arguments; never name-only matching.  
**Current state:** Valuable anti-confused-deputy design, but its dependencies are older approval/CodeRegistry architecture.  
**SPEC:** [SPEC-080226-510f](../../../specs/SPEC-080226-510f-content-addressed-tool-approval-rules.md)

## SPEC-081226-034b: Package ownership
**Status:** AC Defined  
**Next steps:** Treat as canonical M1 package-boundary checklist. Add direct tests/architecture checks for every AC and remove pre-1.0 compatibility language where it would preserve obsolete package surfaces.  
**Current state:** Source anchors exist, but front matter has no tests. AC Defined is accurate.  
**SPEC:** [SPEC-081226-034b](../../../specs/SPEC-081226-034b-package-ownership-dependency-direction.md)

## SPEC-081226-69ee: Graph and Node execution
**Status:** AC Defined  
**Next steps:** Use as the canonical M1 Graph convergence checklist. Bind parity/reachability tests proving Graph domain semantics survive while all physical execution uses canonical Runs. Retire GraphRun/Builders/Task executors.  
**Current state:** Strong AC-module mapping, no bound tests.  
**SPEC:** [SPEC-081226-69ee](../../../specs/SPEC-081226-69ee-graph-node-execution-model.md)

## SPEC-081226-6b46: Capability/Provider/Binding/Invocation
**Status:** AC Defined  
**Next steps:** Highest-priority M1/M2 evidence target: prove real production callers, authorization ceiling, provider selection, credential resolution, Invocation persistence, fallback non-widening, harness/provider lifecycle, and Run correlation.  
**Current state:** Canonical capability architecture with source anchors but no tests in front matter; August 30 evidence showed Invocation initially had no production caller, while September work has since begun closing that gap.  
**SPEC:** [SPEC-081226-6b46](../../../specs/SPEC-081226-6b46-capability-provider-binding-invocation.md)

## SPEC-081226-6e34: Scoped grants / deny-wins
**Status:** AC Defined  
**Next steps:** Highest-priority M2 authorization checklist. Bind tests for ancestry, additive child grants, deny inheritance, object/resource visibility, Persona non-authority, and Binding authorization.  
**Current state:** Canonical authorization semantics are defined and source-anchored; completion evidence is not yet bound.  
**SPEC:** [SPEC-081226-6e34](../../../specs/SPEC-081226-6e34-hierarchical-permissions.md)

## SPEC-081226-7248: Event and checkpoint model
**Status:** AC Defined  
**Next steps:** Prove durable event/outbox/occurrence behavior, bounded/redacted payloads, canonical correlation, and GraphContinuationStore recovery. Remove the unused competing checkpoint store.  
**Current state:** Canonical durable-history/recovery spec with strong AC modules but no bound tests.  
**SPEC:** [SPEC-081226-7248](../../../specs/SPEC-081226-7248-event-checkpoint-model.md)

## SPEC-081226-9944: Product hierarchy / ownership
**Status:** AC Defined  
**Next steps:** Use as M1 ownership checklist: every durable object carries Workspace; project-scoped objects carry one Project; Templates are the intentional Workspace-wide reusable exception; execution/capability objects follow canonical ownership.  
**Current state:** Canonical product model, source-anchored but not fully evidenced.  
**SPEC:** [SPEC-081226-9944](../../../specs/SPEC-081226-9944-canonical-product-hierarchy-and-ownership.md)

## SPEC-081226-a66b: Run → NodeRun → Attempt
**Status:** AC Defined  
**Next steps:** Treat as the central M1 lifecycle checklist. Bind conformance tests across stores/executors for transitions, terminal derivation, retries, cancellation, parent/child Runs, and no competing post-admission lifecycle.  
**Current state:** This is the canonical execution spine and has the richest AC-module map in the tranche; tests still need explicit lifecycle evidence binding.  
**SPEC:** [SPEC-081226-a66b](../../../specs/SPEC-081226-a66b-run-noderun-attempt-lifecycle.md)

## SPEC-081226-bb3a: Template/object/provenance
**Status:** AC Defined  
**Next steps:** Finish exact-version pinning, instantiate/save-as-template provenance, immutable history, and current Template candidate/promotion semantics.  
**Current state:** One direct test is bound; broader AC evidence remains incomplete.  
**SPEC:** [SPEC-081226-bb3a](../../../specs/SPEC-081226-bb3a-template-object-provenance-semantics.md)

## SPEC-081226-e626: Persona surface
**Status:** AC Defined  
**Next steps:** Prove Persona remains preference/config only, contributes no authority, and provider/capability preferences filter only within authorized candidates. Keep inert UI modes deleted.  
**Current state:** Canonical Persona semantics are source-anchored, not fully evidenced.  
**SPEC:** [SPEC-081226-e626](../../../specs/SPEC-081226-e626-persona-surface-model.md)

## SPEC-081426-1f7c: ExecutionRuntime
**Status:** AC Defined  
**Next steps:** Bind conformance tests for capacity, cancellation, deadlines, Attempt identity, recursive events, slot accounting, and separation of mechanics from domain terminalization.  
**Current state:** Canonical physical-execution contract with extensive AC modules but no tests in front matter.  
**SPEC:** [SPEC-081426-1f7c](../../../specs/SPEC-081426-1f7c-execution-runtime-contract.md)

## SPEC-081426-b1d3: Project scope tree
**Status:** AC Defined  
**Next steps:** Bind tests for immutable Root Project, acyclic same-Workspace tree, downward resource visibility, additive child grants, deny inheritance, move validation, and fail-closed deletion.  
**Current state:** Canonical Project semantics are well mapped to source but not fully evidenced.  
**SPEC:** [SPEC-081426-b1d3](../../../specs/SPEC-081426-b1d3-project-scope-tree.md)

## SPEC-082126-3c9d: PII evasion normalization
**Status:** Implemented  
**Next steps:** Keep regression/property tests and ensure every current Sentinel PII boundary uses the canonical normalization path.  
**Current state:** Direct tests and AC modules support a credible narrow Implemented claim.  
**SPEC:** [SPEC-082126-3c9d](../../../specs/SPEC-082126-3c9d-pii-evasion-normalization.md)

## SPEC-082126-5f6a: Warden L3 judge failure semantics
**Status:** Implemented  
**Next steps:** Preserve fail-closed semantics whenever L3 is actually invoked; provider failure/malformed output cannot become safe.  
**Current state:** Narrow, direct, tested security contract.  
**SPEC:** [SPEC-082126-5f6a](../../../specs/SPEC-082126-5f6a-warden-llm-judge-failure-semantics.md)

## SPEC-082126-7a31: Tool argument resource limits
**Status:** Implemented  
**Next steps:** Keep limits ahead of expensive schema traversal/execution and ensure canonical Invocation/tool surfaces cannot bypass them.  
**Current state:** Narrow tested Sentinel control with direct AC mapping.  
**SPEC:** [SPEC-082126-7a31](../../../specs/SPEC-082126-7a31-tool-argument-resource-limits.md)

## SPEC-082226-2a10: Resource security floors
**Status:** Implemented  
**Next steps:** Keep configurable values above hard security floors and expose effective policy in health/diagnostics without permitting routine tuning below the floor.  
**Current state:** Direct tests cover settings, enforcement, circuit breaker, and server health.  
**SPEC:** [SPEC-082226-2a10](../../../specs/SPEC-082226-2a10-resource-security-floors.md)
