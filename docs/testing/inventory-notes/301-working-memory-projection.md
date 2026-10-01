---
inventory-delta:
  packages/maistro-core/tests: +46
---
# 301 per-Workspace working-memory projection (Ladybug-shaped hot layer)

Implements #301 / ADR-082226-5104 §5–8: a MAIstro-owned `WorkingMemory`
protocol, a per-Workspace indexed projection behind it (BM25 inverted index,
write-time stored embeddings, entity/mention/co-occurrence graph), a manager
with lazy idempotent hydration from the authoritative episodic store, idle-TTL
eviction and discard-and-rebuild, and the Layer 1 / Layer 4 wiring in
`DefaultContextAssemblyPolicy` — Layer 4 stops returning the placeholder `""`
for a populated Workspace. Design and the ADR-039 dependency review (no
`ladybugdb` dependency; it does not resolve from the registry) are in
`docs/architecture/working-memory.md`.

All additions, no removals:

- `packages/maistro-core/tests/memory/working/test_working_memory.py` —
  protocol conformance, idempotent hydration, BM25-vs-overlap ranking, the
  one-embed-per-read proof, scope preservation (agent/org/project/weight),
  update re-index + re-embed consistency, failed-embed degradation (lexical
  only, never stale vector), model-identity drift dropping stale vectors,
  entity MentionedIn/co-occurrence/traversal, delete pruning, cross-Workspace
  isolation with identical ids and entity names, evict/rehydrate, reset,
  TTL sweep, hydration-read failure recorded, backend init failure raising
  `WorkingMemoryError`, rebuild recovery, and the read-only Dreaming
  candidate set.
- `packages/maistro-core/tests/memory/working/test_working_context_layers.py` —
  Layer 1 hot path (with the empty-query and degradation fallbacks), scope
  narrowing through the policy, real Layer 4 graph context for a populated
  Workspace with provenance rendered, project narrowing, empty/degraded
  honesty (returns `""`, never fabricates), `assemble` integration, and the
  no-manager compatibility path.
