"""Hybrid BM25 + vector memory retrieval ranking (ADR-080 part D / SPEC-243)."""

from __future__ import annotations

from collections.abc import Callable

from maistro.memory.types import EpisodicMemory

LexicalFn = Callable[[str, EpisodicMemory], float]
VectorFn = Callable[[str, EpisodicMemory], float]


def score(
    query: str,
    memory: EpisodicMemory,
    *,
    lexical_fn: LexicalFn,
    vector_fn: VectorFn,
) -> float:
    """Hybrid score: (lexical relevance + vector similarity) * current memory weight."""
    return (lexical_fn(query, memory) + vector_fn(query, memory)) * memory.weight


def rank(
    query: str,
    memories: list[EpisodicMemory],
    *,
    k: int,
    lexical_fn: LexicalFn,
    vector_fn: VectorFn,
) -> list[EpisodicMemory]:
    """Score every memory and return the top-k, descending."""
    scored = sorted(
        memories,
        key=lambda m: score(query, m, lexical_fn=lexical_fn, vector_fn=vector_fn),
        reverse=True,
    )
    return scored[:k]
