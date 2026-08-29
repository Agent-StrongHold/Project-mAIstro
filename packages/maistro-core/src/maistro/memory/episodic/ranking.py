"""Hybrid lexical + vector memory retrieval ranking (ADR-080 part D / SPEC-243).

`score` and `rank` are SPEC-243's shape verbatim, with the two component
functions injected so the formula is testable without an index or an embedding
call. What is new here is that the components have *defaults*, because the
formula having one home did not stop three callers from each inventing their own
lexical term (#622):

* `InMemoryEpisodicStore.retrieve` scored `overlap_count * weight`;
* `ScoredEpisodicRetrieval` scored `(overlap_ratio + cosine) * weight`;
* `DefaultContextAssemblyPolicy.layer1` did not rank at all.

The count and the ratio order a lexical-only query identically — the divisor is
constant per query — so the difference is not ordering, it is *scale*, and scale
is the whole point once ADR-080's second term is present. `keyword_overlap` is
the ratio, bounded in [0, 1] like the cosine it is added to. Against a raw
count, a bounded similarity cannot outweigh even one matched word, so the vector
half is decorative: it can reorder memories that tie lexically and nothing else.
Adding two terms only means something if they share a range.
"""

from __future__ import annotations

from collections.abc import Callable

from maistro.memory.types import EpisodicMemory

LexicalFn = Callable[[str, EpisodicMemory], float]
VectorFn = Callable[[str, EpisodicMemory], float]


def keyword_overlap(query: str, memory: EpisodicMemory) -> float:
    """Share of the query's distinct words the memory contains, in [0, 1].

    The default lexical term until a real BM25 or `pg_trgm` index exists to back
    one (SPEC-243 names both as the eventual source and says to reuse whichever
    index the store already has — today the store has neither).
    """
    query_words = {w for w in query.lower().split() if w}
    if not query_words:
        return 0.0
    content_words = {w for w in memory.content.lower().split() if w}
    if not content_words:
        return 0.0
    return len(query_words & content_words) / len(query_words)


def no_vector(query: str, memory: EpisodicMemory) -> float:
    """The vector term when there is no embedding client.

    An explicit zero rather than an optional argument: the formula is a sum of
    two terms, and a caller without embeddings should still be adding two terms
    — one of which happens to be zero — instead of running a different formula
    that merely resembles this one.
    """
    return 0.0


def score(
    query: str,
    memory: EpisodicMemory,
    *,
    lexical_fn: LexicalFn = keyword_overlap,
    vector_fn: VectorFn = no_vector,
) -> float:
    """Hybrid score: (lexical relevance + vector similarity) * current memory weight."""
    return (lexical_fn(query, memory) + vector_fn(query, memory)) * memory.weight


def rank(
    query: str,
    memories: list[EpisodicMemory],
    *,
    k: int,
    lexical_fn: LexicalFn = keyword_overlap,
    vector_fn: VectorFn = no_vector,
    min_score: float = 0.0,
) -> list[EpisodicMemory]:
    """Score every memory and return the top-k, descending.

    Memories scoring at or below `min_score` are dropped rather than ranked
    last. A zero score means the query matched nothing in the memory on either
    term, and padding a prompt out to `k` with text the query has no relation to
    spends budget that a relevant memory could have had.
    """
    scored = [(score(query, m, lexical_fn=lexical_fn, vector_fn=vector_fn), m) for m in memories]
    kept = [(s, m) for s, m in scored if s > min_score]
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [m for _s, m in kept[:k]]
