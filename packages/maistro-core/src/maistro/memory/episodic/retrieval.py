"""Scored episodic retrieval with embedding reranking (ADR-080 part D / SPEC-243).

Two-stage: the store recalls the scoped candidate pool, this reranks it by the
hybrid score. That split is why this can no longer read `store._memories`, which
is what it did — a private list that exists on `InMemoryEpisodicStore` and on no
other implementation, so the ranking ADR-080 mandates worked against the test
double and would have raised `AttributeError` against anything durable (#622).
The pool now comes from `EpisodicStore.list_by_scope`, which every
implementation of the protocol has to answer.

The pool is the store's judgement and the order is this class's: a store that
can rank better than a Python loop — one with a `pg_trgm` index and a pgvector
column — reranks nothing and implements `retrieve` itself. What it must not do
is invent a fourth spelling of the formula, which is why the formula lives in
`ranking` and this file supplies only the embedding half.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maistro.memory.episodic.ranking import VectorFn, keyword_overlap, rank
from maistro.memory.learnings.embeddings import cosine_similarity

if TYPE_CHECKING:
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.protocols.memory import EpisodicStore
    from maistro.types.memory import EpisodicMemory

logger = logging.getLogger(__name__)

#: How many scoped memories to recall per requested result before reranking.
#:
#: Reranking cannot promote a memory the recall stage never returned, so the
#: pool has to be wider than the answer; it also cannot be unbounded, because
#: the vector half embeds every candidate. Ten is a recall/cost trade-off, not a
#: measured optimum — a store that ranks in the database does not pay it at all.
_POOL_FACTOR = 10


class ScoredEpisodicRetrieval:
    """Reranks an `EpisodicStore`'s scoped recall by the hybrid score.

    Score = (lexical relevance + vector similarity) * memory weight
    (ADR-080 part D). Higher-weight memories (LESSON, REGRET, WISDOM) rank above
    lower ones at equal relevance.
    """

    def __init__(
        self,
        store: EpisodicStore,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._store = store
        self._embeddings = embedding_client

    async def retrieve(
        self,
        query: str,
        *,
        org_id: str | None = None,
        team_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Retrieve relevant memories, scope-filtered and scored."""
        candidates = await self._store.list_by_scope(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
            project_id=project_id,
            min_weight=min_weight,
            limit=max(limit, 1) * _POOL_FACTOR,
        )
        if not candidates:
            return []

        vector_fn = await self._vector_term(query, candidates)
        return rank(query, candidates, k=limit, lexical_fn=keyword_overlap, vector_fn=vector_fn)

    async def _vector_term(self, query: str, candidates: list[EpisodicMemory]) -> VectorFn:
        """The vector half of the score, resolved to a plain lookup.

        Embedding is async and the formula is not, so every similarity is
        computed here and the returned function only reads the result. Any
        failure — no client, an unembeddable query, one memory the client
        chokes on — degrades to zero for that term rather than failing the
        recall: a memory ranked on keywords alone is worse than one ranked on
        both, and both are better than a prompt with no memory in it.
        """
        similarities: dict[str, float] = {}
        query_vec = await self._embed(query)
        if query_vec is not None:
            for memory in candidates:
                memory_vec = await self._embed(memory.content)
                if memory_vec is not None:
                    similarities[memory.memory_id] = cosine_similarity(query_vec, memory_vec)

        def vector_fn(_query: str, memory: EpisodicMemory) -> float:
            return similarities.get(memory.memory_id, 0.0)

        return vector_fn

    async def _embed(self, text: str) -> list[float] | None:
        """The embedding, or None when there is not a usable one.

        An all-zero vector is treated as absent, not as a vector: cosine
        similarity against it is 0.0 for everything, which is a term that adds
        nothing while looking like it was computed.
        """
        if self._embeddings is None:
            return None
        try:
            vector = await self._embeddings.embed(text)
        except Exception:
            logger.warning("Embedding failed; falling back to keyword-only ranking")
            return None
        if not vector or all(value == 0.0 for value in vector):
            return None
        return vector
