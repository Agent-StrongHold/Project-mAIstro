# July Architecture Specs

## SPEC-070226-2b70: Observability replay / PII tiers
**Status:** Proposed  
**Next steps:** Rewrite proxy/interception points around governed model egress, Capability Invocation, canonical Run provenance, and current Event/audit persistence.  
**Current state:** Pure replay/tier modules and tests exist, but governing ADR-055 remains Proposed and older tool/recipe boundaries are stale.  
**SPEC:** [SPEC-070226-2b70](../../../specs/SPEC-070226-2b70-observability-replay-pii-tiers.md)

## SPEC-070226-3bbd: TextGrad-style node attribution
**Status:** Proposed  
**Next steps:** Map attribution to canonical Graph Node/NodeRun and Evolve genomes; validate on held-out multi-node pipelines before mutation.  
**Current state:** Research-backed Evolve enhancement, not current architecture.  
**SPEC:** [SPEC-070226-3bbd](../../../specs/SPEC-070226-3bbd-evolve-textgrad-node-attribution.md)

## SPEC-070226-5ce3: Evolve island populations
**Status:** Proposed  
**Next steps:** Integrate only after canonical Evolve candidate/version/promotion semantics are settled; benchmark diversity/fitness benefit against simpler population strategies.  
**Current state:** Optimization proposal, not a platform dependency.  
**SPEC:** [SPEC-070226-5ce3](../../../specs/SPEC-070226-5ce3-evolve-island-model-population.md)

## SPEC-070226-6489: Identity lifecycle
**Status:** Proposed  
**Next steps:** Replace DID-first AgentIdentity/CapabilityToken authority with canonical principals, scoped grants/delegation, sessions, Workspace membership, and current approval design.  
**Current state:** Correctly returned to Proposed because ADR-084 is Proposed; current identity substrate has moved on.  
**SPEC:** [SPEC-070226-6489](../../../specs/SPEC-070226-6489-identity-lifecycle.md)

## SPEC-070226-8239: Canvas server/consumer cutover
**Status:** Proposed  
**Next steps:** Directly cut Design Studio/Workspace consumers to canonical Canvas capability/server composition and delete legacy Canvas execution/API paths. Remove ADR-076 compatibility requirements pre-1.0.  
**Current state:** Server boundary only partially wired; product framing has already been corrected.  
**SPEC:** [SPEC-070226-8239](../../../specs/SPEC-070226-8239-canvas-studio-cutover.md)

## SPEC-070226-82ea: Builders DAG
**Status:** Proposed  
**Next steps:** Keep stage/gate/revision semantics but execute solely through canonical Graph/Run; remove Builders-owned lifecycle/traversal authority.  
**Current state:** Governing ADR-099 is Proposed and current convergence work has already moved Builders toward canonical Runs.  
**SPEC:** [SPEC-070226-82ea](../../../specs/SPEC-070226-82ea-builders-dag.md)

## SPEC-070226-83bd: OPRO prompt history
**Status:** Proposed  
**Next steps:** Add bounded prior-candidate/score history to Evolve reflection only if benchmarked improvement justifies token cost; store history in canonical candidate/evaluation records.  
**Current state:** Research optimization proposal.  
**SPEC:** [SPEC-070226-83bd](../../../specs/SPEC-070226-83bd-evolve-opro-meta-prompt-history.md)

## SPEC-070226-af02: P1 resilience/control
**Status:** Proposed  
**Next steps:** Split depth, compaction, retry, steering, and rate concerns onto their canonical Run/Invocation/context/provider boundaries rather than implementing ADR-066's GraphRun-era bundle.  
**Current state:** Tests exist for some primitives, but governing ADR remains Proposed and boundary ownership is stale.  
**SPEC:** [SPEC-070226-af02](../../../specs/SPEC-070226-af02-p1-resilience-control.md)

## SPEC-070226-b234: Events/triggers/reactor
**Status:** Proposed  
**Next steps:** Rewrite trigger execution to durable occurrence claims plus canonical Run/Invocation admission while preserving the implemented durable log/trigger/cursor work.  
**Current state:** Strong implementation slices exist; governing ADR-086 remains Proposed because its old recipe/task execution target is stale.  
**SPEC:** [SPEC-070226-b234](../../../specs/SPEC-070226-b234-events-triggers-reactor.md)

## SPEC-070226-b624: Orchestrator waves
**Status:** Proposed  
**Next steps:** Retire independent SuperPlanner/MasterOrchestrator execution; migrate useful ensemble/planning logic into canonical Graph planning/child Runs.  
**Current state:** Governing ADR-071 is Proposed and based on retired execution mechanisms.  
**SPEC:** [SPEC-070226-b624](../../../specs/SPEC-070226-b624-orchestrator-waves.md)

## SPEC-070226-bfa3: Reflexion episodic memory
**Status:** Proposed  
**Next steps:** If retained, write reflections through canonical durable episodic memory with explicit exposure mode, provenance, retrieval budget, and evaluation of whether reflections improve held-out outcomes.  
**Current state:** Useful Evolve experiment, not baseline memory behavior.  
**SPEC:** [SPEC-070226-bfa3](../../../specs/SPEC-070226-bfa3-evolve-reflexion-episodic-memory.md)

## SPEC-070226-c4f8: Hierarchical orchestration / portability
**Status:** Proposed  
**Next steps:** Converge onto harness-as-Provider/Binding/Invocation and canonical child Runs; consolidate duplicate ADR-101/f383 lineage.  
**Current state:** Current harness architecture has moved beyond its direct hierarchy/session assumptions.  
**SPEC:** [SPEC-070226-c4f8](../../../specs/SPEC-070226-c4f8-hierarchical-orchestration.md)

## SPEC-070226-cb8d: LLM provider registry
**Status:** Proposed  
**Next steps:** Rewrite around current governed provider registry, credentials, fallback chain, health/quota outcomes, and Invocation evidence. Split embeddings out.  
**Current state:** Tests cover an older provider/router design; actual model-routing architecture has since advanced.  
**SPEC:** [SPEC-070226-cb8d](../../../specs/SPEC-070226-cb8d-llm-provider-registry.md)

## SPEC-070226-fbe3: Deployment topology / DR
**Status:** Proposed  
**Next steps:** Separate scratch-deploy application topology from persistent-data backup/restore; remove old/new-version coexistence requirements and stale ADR-087 assumptions.  
**Current state:** Governing ADR-081 is Proposed and needs the same pre-1.0 rewrite.  
**SPEC:** [SPEC-070226-fbe3](../../../specs/SPEC-070226-fbe3-deployment-topology.md)

## SPEC-070426-457b: Canvas structured exporters
**Status:** Accepted  
**Next steps:** Remeasure PPTX/HTML export tests and converge renderer registration onto canonical capability providers. Promote if the narrow export contract is complete.  
**Current state:** Healthy, concrete Canvas ability with direct tests and no external dependency.  
**SPEC:** [SPEC-070426-457b](../../../specs/SPEC-070426-457b-canvas-structured-exporters.md)

## SPEC-070426-a22b: Renderer capability substrate
**Status:** Accepted  
**Next steps:** Map slots/providers/discovery to canonical Provider/Binding/Invocation. Absence may hide an unavailable option, but a selected capability must return explicit execution evidence/failure.  
**Current state:** Strong conceptual predecessor to the canonical capability model.  
**SPEC:** [SPEC-070426-a22b](../../../specs/SPEC-070426-a22b-renderer-capability-substrate.md)

## SPEC-070426-6ea8: Open Design renderer provider
**Status:** Accepted  
**Next steps:** Reconcile local-daemon discovery/execution with outbound policy, current Binding authorization, and Invocation evidence; remeasure provider tests.  
**Current state:** Concrete optional renderer implementation with direct tests.  
**SPEC:** [SPEC-070426-6ea8](../../../specs/SPEC-070426-6ea8-open-design-renderer-provider.md)

## SPEC-070626-17d0: ConductorSeed recovery/storage
**Status:** Proposed  
**Next steps:** Do not implement as baseline identity. Revisit only if optional seed capability remains desired after canonical-principal identity work; then threat-model recovery/storage independently.  
**Current state:** Optional crypto capability.  
**SPEC:** [SPEC-070626-17d0](../../../specs/SPEC-070626-17d0-conductor-seed-slip39-and-secret-store.md)

## SPEC-070626-4ec8: DID/VC types
**Status:** Proposed  
**Next steps:** Treat DID/VC as optional federation/provenance types, never canonical runtime principals or authorization. Reconcile with current approval/identity choices first.  
**Current state:** Depends on Proposed identity lifecycle and older mandatory-DID assumptions.  
**SPEC:** [SPEC-070626-4ec8](../../../specs/SPEC-070626-4ec8-identity-vc-did-document.md)

## SPEC-070626-5341: Local CA from seed
**Status:** Proposed  
**Next steps:** Do not implement until ADR-026 is reconciled. The spec itself documents a verified derivation/algorithm conflict with its governing ADR.  
**Current state:** Explicitly unresolved migration artifact.  
**SPEC:** [SPEC-070626-5341](../../../specs/SPEC-070626-5341-local-ca-from-seed.md)

## SPEC-070626-7912: Crypto spending policy
**Status:** Proposed  
**Next steps:** Revisit only if optional agent crypto becomes active; map spending authority to canonical principals, Bindings, explicit approvals, and current crypto-bound approval evidence.  
**Current state:** Optional future capability.  
**SPEC:** [SPEC-070626-7912](../../../specs/SPEC-070626-7912-crypto-ops-spending-policy.md)

## SPEC-070626-9460: Hardware signing protocol
**Status:** Proposed  
**Next steps:** Revisit after deciding whether hardware-backed signing is needed for current approval/credential architecture. Do not make it baseline auth.  
**Current state:** Optional future capability.  
**SPEC:** [SPEC-070626-9460](../../../specs/SPEC-070626-9460-hardware-signing-device-protocol.md)

## SPEC-070626-a675: Networking identity substrate
**Status:** Proposed  
**Next steps:** Split transport from authentication and prohibit arbitrary upstream headers from becoming principals without an authenticated trusted-ingress binding.  
**Current state:** Implements an older ADR-029 model that the ADR audit already flagged for auth reconciliation.  
**SPEC:** [SPEC-070626-a675](../../../specs/SPEC-070626-a675-networking-identity-substrate.md)
