"""Scored episodic retrieval with embedding reranking.

Hybrid lexical (keyword overlap) + vector (embedding cosine) ranking, scaled
by the memory's confidence weight (ADR-080 part D / SPEC-243).

Ported from Stronghold.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maistro.memory.learnings.embeddings import cosine_similarity
from maistro.memory.scopes import build_scope_filter, matches_scope

if TYPE_CHECKING:
    from maistro.memory.episodic.store import InMemoryEpisodicStore
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.types.memory import EpisodicMemory

logger = logging.getLogger(__name__)


class ScoredEpisodicRetrieval:
    """Retrieves episodic memories with scope filtering and hybrid similarity scoring.

    Score = (lexical_relevance + vector_similarity) * memory_weight (ADR-080 part D).
    Higher weight memories (LESSON, REGRET, WISDOM) rank above lower ones.
    """

    def __init__(
        self,
        store: InMemoryEpisodicStore,
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
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Retrieve relevant memories, scope-filtered and scored."""
        scope_filters = build_scope_filter(
            agent_id=agent_id,
            user_id=user_id,
            team_id=team_id,
            org_id=org_id,
        )

        all_memories = [m for m in self._store._memories if not m.deleted]
        scoped = [m for m in all_memories if matches_scope(m, scope_filters)]

        if not scoped:
            return []

        scored: list[tuple[float, EpisodicMemory]] = []

        query_vec: list[float] | None = None
        if self._embeddings:
            try:
                query_vec = await self._embeddings.embed(query)
                if all(v == 0.0 for v in query_vec):
                    query_vec = None
            except Exception:
                logger.warning("Embedding query failed, falling back to keyword retrieval")
                query_vec = None

        query_words = set(query.lower().split())

        for mem in scoped:
            lexical = self._keyword_similarity(query_words, mem.content)
            vector = 0.0
            if query_vec:
                try:
                    mem_vec = await self._embeddings.embed(mem.content)  # type: ignore[union-attr]
                    vector = cosine_similarity(query_vec, mem_vec)
                except Exception:
                    vector = 0.0

            score = (lexical + vector) * mem.weight
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    @staticmethod
    def _keyword_similarity(query_words: set[str], content: str) -> float:
        """Simple word overlap ratio."""
        content_words = set(content.lower().split())
        if not query_words or not content_words:
            return 0.0
        overlap = len(query_words & content_words)
        return overlap / len(query_words)
