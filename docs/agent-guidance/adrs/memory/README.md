# Memory ADRs

Progressive-disclosure index for ADRs governing durable memory, recall, learning, context assembly, and related persistence behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-011: Memory engine + session factory wiring

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-011 implementation work remains. Reconcile SPEC-212's stale `Proposed` lifecycle status against the same implementation/test evidence during the specification audit.  
**Current state:** Cached DB-optional async engine/session-factory wiring is implemented, the server lifespan initializes and disposes the engine, cache reset is wired, and focused tests cover configured/unconfigured engine creation plus usable async sessions. ADR-011 was promoted from `Accepted` to `Implemented` during this audit based on direct code and test evidence.  
**ADR:** [ADR-011: Memory engine + session factory wiring](../../../adr/ADR-011-memory-engine.md)

## ADR-013: Memory types — Learning, EpisodicMemory, Outcome, scopes, tiers

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-013 implementation work remains. Later memory ADRs/specs should continue to treat `maistro.types.memory` and the shared scope rule as canonical rather than re-declaring these primitives.  
**Current state:** The seven-tier memory types, weight bounds, Learning/Outcome/EpisodicMemory domain types, and tenant-aware scope filtering are implemented and directly tested. Subsequent work has extended these types and added shared Python/SQL scope-conformance enforcement without invalidating ADR-013's original invariants.  
**ADR:** [ADR-013: Memory types — Learning, EpisodicMemory, Outcome, scopes, tiers](../../../adr/ADR-013-memory-types.md)

## ADR-014: Memory protocols

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-014 implementation work remains. New memory stores should continue to satisfy the canonical protocols rather than introducing store-specific caller contracts.  
**Current state:** Runtime-checkable LearningStore, EpisodicStore, and OutcomeStore contracts are implemented and their in-memory implementations pass direct protocol-conformance tests. The protocol module has subsequently expanded to cover additional memory capabilities while preserving these original dependency-injection boundaries.  
**ADR:** [ADR-014: Memory protocols](../../../adr/ADR-014-memory-protocols.md)

## ADR-015: Learning type + InMemoryLearningStore

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-015 implementation work remains. Reconcile SPEC-216's stale lifecycle status during the specification audit and preserve the store's org-isolation/dedup invariants in durable implementations.  
**Current state:** InMemoryLearningStore implements and directly tests same-org Jaccard deduplication, cross-org isolation, FIFO capacity eviction, relevance filtering, usage tracking, threshold promotion, and promoted-only retrieval. The implementation has since gained additional outcome/effectiveness behavior without invalidating ADR-015's original contract.  
**ADR:** [ADR-015: Learning type + InMemoryLearningStore](../../../adr/ADR-015-learning-store.md)

## ADR-016: EpisodicMemory + 7-tier weights + InMemoryEpisodicStore

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-016 implementation work remains. Later episodic-memory work should preserve tier floors, scope isolation, soft-delete exclusion, and weight-sensitive ranking while extending the retrieval model.  
**Current state:** Seven-tier episodic memory, bounded reinforcement/decay, scoped retrieval, stored reinforcement, and deletion filtering are implemented and directly tested. Retrieval ranking has evolved to a shared hybrid lexical/vector scorer, but relevance remains weight-sensitive and the original ADR invariants are preserved.  
**ADR:** [ADR-016: EpisodicMemory + 7-tier weights + InMemoryEpisodicStore](../../../adr/ADR-016-episodic-store.md)

## ADR-017: Outcome + InMemoryOutcomeStore

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-017 implementation work remains. Later outcome/economics/telemetry work should preserve bounded recording, time-window semantics, and tenant-scoped aggregation while extending the record.  
**Current state:** Outcome recording, bounded FIFO eviction, completion-rate calculation, model breakdown, time-window filtering, and org isolation are implemented and directly tested. The Outcome record/store has since expanded with richer execution, billing, feedback, and provenance telemetry without invalidating ADR-017's original guarantees.  
**ADR:** [ADR-017: Outcome + InMemoryOutcomeStore](../../../adr/ADR-017-outcome-store.md)

## ADR-034: Memory Canonical Ownership

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Keep the single-owner invariant, but reconcile the historical cross-repo/product migration table with current monorepo package/adaptor boundaries and the newer memory ADR/spec family beyond ADR-011–017. New memory architecture must continue to land in the canonical shared memory layer rather than being silently redefined by product packages.  
**Current state:** ADR-034 remains active architectural governance: shared memory types, protocols, persistence, retrieval, and evolution semantics have one canonical owner, while product-specific surfaces/adapters parameterize that architecture. The original four-repo migration narrative is historical after consolidation, but the anti-drift ownership rule remains current.  
**ADR:** [ADR-034: Memory Canonical Ownership](../../../adr/ADR-034-memory-canonical-ownership.md)

## ADR-048: Session Search — Episodic memory inspector endpoint

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Build the missing route/storage integration on top of SPEC-250: canonical server endpoint, current principal/Workspace/session authorization, cross-scope leak tests, durable Postgres/SQLite search backend and stable cursor semantics, required performance evidence, and `sessions.search` observability. Replace the historical profile-middleware assumption with current scope authority. Promote only after the complete ADR contract is evidenced.  
**Current state:** SPEC-250 implements and tests the pure search/snippet/cursor algorithm, but explicitly excludes the HTTP route, authorization/scoping boundary, real storage/search backend, OTel span, and several ADR-level acceptance criteria. ADR-048 was previously rolled back from Implemented to Accepted for exactly this evidence gap, and that status remains correct.  
**ADR:** [ADR-048: Session Search — Episodic memory inspector endpoint](../../../adr/ADR-048-session-search.md)
