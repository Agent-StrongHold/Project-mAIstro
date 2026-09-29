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

## ADR-057: Memory exposure mode — configurable system-managed vs agent-managed

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Complete SPEC-062126-6a31 on the current agent/configuration architecture: mandatory explicit exposure-mode declaration with no compatibility fallback, concrete store read/write/promote enforcement, fail-fast agent construction where applicable, HYBRID block enforcement, observability/denial events, and no product-identity branching. Replace its ADR-053 RecipeOverlay dependency if that abstraction is superseded.  
**Current state:** The pure exposure-mode enforcement primitive exists, and the follow-up spec explicitly rejected ADR-057's old backwards-compatible implicit default in favor of immediate mandatory declaration, which matches current pre-1.0 policy. The implementing SPEC remains Accepted with its integration ACs unchecked, so the ADR's earlier Implemented claim was correctly rolled back.  
**ADR:** [ADR-057: Memory exposure mode — configurable system-managed vs agent-managed](../../../adr/ADR-057-memory-exposure-mode.md)

## ADR-080: Memory Dynamics — decay, reinforcement, tiers, consolidation, and cross-scope sharing

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Remeasure the ADR-level contract across SPEC-240/241/242/243 and SPEC-062126-5d56, focusing on **reachability**, not just pure functions: time-based decay execution, overnight/batch consolidation and contradiction-triggered consolidation, current-principal consent for scope widening, cross-agent read enforcement, and hybrid retrieval ranking in the real recall path. Reconcile old scope examples with canonical Workspace/principal semantics. Promote only when the full dynamics are actually exercised.  
**Current state:** The child-spec family implements substantial mechanics: decay/feedback, consolidation, sharing/consent, ranking, and follow-up strategy/resolution primitives. The remaining uncertainty is whether all ADR behaviors are connected to production scheduling/events/read paths, especially overnight consolidation and scope-consent workflow. The earlier Implemented claim was therefore correctly rolled back pending strict evidence.  
**ADR:** [ADR-080: Memory Dynamics — decay, reinforcement, tiers, consolidation, and cross-scope sharing](../../../adr/ADR-080-memory-dynamics.md)

## ADR-091: Memory model reconciliation — storage types vs context assembly layers

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **Create an amending/successor decision for hard context-window safety.** Preserve the storage-vs-assembly distinction and ranked whole-memory packing, but change "always include regardless of token budget" so protected memories have highest eviction priority rather than permission to exceed the model/provider's absolute context window. When protected context cannot fit, compact/summarize/escalate explicitly; never overspend a physical context limit. Also reconcile Layer-3 cross-user/project wisdom with explicit sharing and Workspace authorization from ADR-080/current principals.  
**Current state:** ContextAssemblyPolicy is implemented and recent #622 work intentionally made ≥0.6 memories overspend the supplied budget. That faithfully implements ADR-091 but exposes a flaw in the decision: model context is a hard resource ceiling, not a soft preference. The ADR's two-level storage-vs-assembly reconciliation remains valuable, while its budget and cross-user visibility rules need correction before being treated as final.  
**ADR:** [ADR-091: Memory model reconciliation — storage types vs context assembly layers](../../../adr/ADR-091-memory-model-layers.md)

## ADR-063026-a91f: Context windows are not memory

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Keep this as validation/research context rather than a competing memory authority. Update its status table to reflect the now-implemented portions of ADR-091/SPEC-244 and the hard-context-window correction identified in this audit. Evaluate algorithmic prompt compression only from measured token/quality data; do not add compression machinery merely because an external article lists it.  
**Current state:** The central thesis is sound and reinforces MAIstro's external-state/query-assemble-commit architecture. The one identified compression gap is an optimization candidate, not an architectural deficiency by itself. This record should cite current memory decisions without freezing their older Proposed-state descriptions.  
**ADR:** [ADR-063026-a91f: Context windows are not memory](../../../adr/ADR-063026-a91f-context-window-memory-architecture-external-validation.md)

## ADR-082226-5104: PostgreSQL durable record + Ladybug working memory

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Treat PostgreSQL/pgvector as the durable system-of-record decision and verify each claimed store is actually wired/reachable. Keep Ladybug strictly as derived/per-Workspace working memory that can be rebuilt and never becomes authoritative for Run, identity, authorization, or durable memory. Reconcile pre-1.0 schema policy with the ADR-087 successor rather than preserving old database shapes.  
**Current state:** This ADR resolves a major storage contradiction: Postgres is infrastructure already paid for and should own durable relational/vector state, while a local graph/working store earns its place only as a distinct derived working-memory tier. Reachability, not schema existence, remains the key completion test.  
**ADR:** [ADR-082226-5104: Storage architecture](../../../adr/ADR-082226-5104-storage-architecture-postgres-durable-ladybug-working-memory.md)

## ADR-082226-d3dd: S3-compatible cold archive tier

**Status:** Superseded  
**Last updated:** 2026-09-29  
**Next steps:** None beyond preserving the supersession link. Do not restore `maistro.memory.archive`; ADR-082226-f436 is the canonical archive decision and the one wired by Container.  
**Current state:** This duplicate same-day archive design was implemented but unreachable and has been deleted. Its useful `list_keys` behavior was ported as scoped listing before removal.  
**ADR:** [ADR-082226-d3dd: Superseded archive tier](../../../adr/ADR-082226-d3dd-s3-compatible-cold-storage-archive-tier.md)

## ADR-082226-f436: Object storage archive tier for cold durable records

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Reconcile status with the implementation the ADR itself says is wired, then prove authoritative rehydration, content-addressed integrity, scope isolation, stub/tombstone behavior, and retention/GC semantics before promotion. Keep archive distinct from backup: archived payload is authoritative cold storage, not a disaster-recovery copy.  
**Current state:** This supersedes d3dd and matches the implementation Container actually wires. The core shape is strong: durable relational identity/scope remains in PostgreSQL while cold payload moves to content-addressed object storage. Lifecycle status appears behind reality and needs evidence reconciliation.  
**ADR:** [ADR-082226-f436: Object storage archive tier](../../../adr/ADR-082226-f436-object-storage-archive-tier-for-cold-memory.md)

## ADR-082326-8194: Memory embedding column and dimensionality

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Preserve same-row scoped vector retrieval and wiring-time dimension validation, but revisit the fixed 1536 dimension only through an explicit destructive pre-1.0 schema decision if a better canonical embedding model warrants it. Continue the producer+consumer-together rule per table so no unused vector columns land. Ensure current embedding Provider/Binding architecture supplies the client without creating a second model-routing path.  
**Current state:** This is a disciplined storage decision: embeddings stay with scoped memory rows in pgvector, HNSW is chosen for interactive recall, and runtime client dimension must match schema before writes. The pre-1.0 posture means the existing 1536 choice is not sacred merely for compatibility if evidence favors changing it.  
**ADR:** [ADR-082326-8194: Memory embedding dimensionality](../../../adr/ADR-082326-8194-memory-embedding-column-and-dimensionality.md)
