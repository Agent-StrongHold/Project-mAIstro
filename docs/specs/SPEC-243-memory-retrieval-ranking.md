---
id: SPEC-243
title: "Hybrid BM25 + vector memory retrieval ranking (ADR-080 part D)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-016
  - maistro-engine#ADR-079
implements:
  - maistro-engine#ADR-080
related:
  - maistro-engine#SPEC-240
  - maistro-engine#SPEC-241
  - maistro-engine#SPEC-242
supersedes: []
blocks: []
blocked-by:
  - maistro-engine#SPEC-240
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/memory/episodic/test_ranking.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-243: Hybrid BM25 + vector memory retrieval ranking

## Context

ADR-080 part (D) pins down the retrieval score as
`(bm25_relevance + vector_similarity) * memory_weight`, replacing ADR-016's under-specified
"weight x word-overlap" retrieval. `packages/maistro-core/src/maistro/memory/episodic/retrieval.py`
exists today but its current ranking does not implement this hybrid formula — it needs the BM25
(or pg_trgm) lexical term and the embedding vector term (per ADR-079's model registry) combined and
scaled by the memory's current `weight` (which SPEC-240 makes time/feedback-dynamic).

## Goals

- A `score(query, memory, *, lexical_fn, vector_fn) -> float` function implementing
  `(lexical_fn(query, memory) + vector_fn(query, memory)) * memory.weight`.
- `rank(query, memories, *, k) -> list[EpisodicMemory]`: scores and returns the top-k memories,
  descending.
- `lexical_fn` backed by BM25 or Postgres `pg_trgm` (whichever the existing episodic store already
  has indexing support for — check `memory/episodic/store.py` before choosing, to avoid introducing
  a second lexical index).
- `vector_fn` backed by the embedding similarity already available via ADR-079's model registry.

## Non-goals

- Decay/reinforcement (SPEC-240, a dependency — retrieval reads `memory.weight`, which SPEC-240
  makes dynamic).
- Consolidation (SPEC-241) and cross-scope consent (SPEC-242) — orthogonal.
- Choosing or training a new embedding model — reuses whatever ADR-079 already registers.
- Query expansion / reranking beyond the single hybrid score formula ADR-080 specifies.

## Decision

```python
def score(
    query: str,
    memory: EpisodicMemory,
    *,
    lexical_fn: Callable[[str, EpisodicMemory], float],
    vector_fn: Callable[[str, EpisodicMemory], float],
) -> float:
    return (lexical_fn(query, memory) + vector_fn(query, memory)) * memory.weight

def rank(
    query: str,
    memories: list[EpisodicMemory],
    *,
    k: int,
    lexical_fn: Callable[[str, EpisodicMemory], float],
    vector_fn: Callable[[str, EpisodicMemory], float],
) -> list[EpisodicMemory]:
    scored = sorted(memories, key=lambda m: score(query, m, lexical_fn=lexical_fn, vector_fn=vector_fn), reverse=True)
    return scored[:k]
```

`lexical_fn`/`vector_fn` are injected (protocol-driven DI, matching SPEC-241's pattern) so the
ranking formula is unit-testable without a real Postgres index or embedding call; the production
wiring in `memory/episodic/retrieval.py` supplies real implementations backed by `pg_trgm`/BM25 and
the ADR-079 embedding client.

## Acceptance criteria

- [x] `score` returns `(lexical_fn + vector_fn) * memory.weight` exactly — a zero-weight memory
      (post-decay, pre-floor) scores at or near zero regardless of lexical/vector match strength.
- [x] `rank` returns memories sorted descending by `score`, truncated to `k`.
- [x] A WISDOM-tier memory (`weight >= 0.9`) with equal lexical/vector relevance to a OBSERVATION-tier
      memory ranks higher, demonstrating reinforced memories surface first.
- [x] `memory/episodic/retrieval.py`'s production `lexical_fn` reuses the existing store's lexical
      index — there is no BM25/`pg_trgm` index in this in-memory store today, so it reuses the
      existing keyword-overlap function rather than adding a second lexical index; the vector term
      reuses the existing `EmbeddingClient`/`cosine_similarity` wiring. Both terms are now **summed**
      (previously either/or) per the ADR-080 formula.

## Testing

- New unit tests for `score`/`rank` using fake `lexical_fn`/`vector_fn` covering the weight-scaling
  behavior and top-k truncation.
- Integration test against `memory/episodic/store.py` exercising the real lexical/vector wiring.

## Open questions

- Whether `lexical_fn`/`vector_fn` should be normalized to a common [0,1] range before summing, or
  left in their native scales (BM25 scores are unbounded) — ADR-080's formula doesn't specify;
  default to normalizing both terms to [0,1] so the multiply-by-weight step behaves predictably,
  revisit if empirical ranking quality suggests otherwise.

## References

- `packages/maistro-core/src/maistro/memory/episodic/retrieval.py`
- `packages/maistro-core/src/maistro/memory/episodic/store.py`
- [ADR-080: Memory Dynamics](../adr/ADR-080-memory-dynamics.md)
- [ADR-079: Model registry, routing, embeddings](../adr/ADR-079-model-registry-routing-embeddings.md)
