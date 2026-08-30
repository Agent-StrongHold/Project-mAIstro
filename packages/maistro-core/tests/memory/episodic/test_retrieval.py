"""Coverage for ScoredEpisodicRetrieval: scope filtering + hybrid lexical/vector scoring."""

from __future__ import annotations

import pytest

from maistro.memory.episodic.ranking import keyword_overlap
from maistro.memory.episodic.retrieval import ScoredEpisodicRetrieval
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.types.memory import EpisodicMemory, MemoryScope, MemoryTier


def make_memory(**kwargs: object) -> EpisodicMemory:
    defaults: dict[str, object] = {
        "memory_id": "m1",
        "tier": MemoryTier.OBSERVATION,
        "content": "the cat sat on the mat",
        "weight": 0.3,
        "scope": MemoryScope.GLOBAL,
    }
    defaults.update(kwargs)
    return EpisodicMemory(**defaults)  # type: ignore[arg-type]


class _StubEmbeddingClient:
    """Returns a fixed vector per text, keyed by exact content match."""

    def __init__(self, vectors: dict[str, list[float]], dimension: int = 3) -> None:
        self._vectors = vectors
        self.dimension = dimension
        self.calls: list[str] = []
        self.fail_on: set[str] = set()

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if text in self.fail_on:
            raise RuntimeError("embedding backend down")
        return self._vectors.get(text, [0.0, 0.0, 0.0])

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


@pytest.fixture
def store() -> InMemoryEpisodicStore:
    return InMemoryEpisodicStore()


class TestScopeFilteringAndEmptyResults:
    async def test_returns_empty_list_when_no_memories_match_scope(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(scope=MemoryScope.USER, user_id="u1"))
        retrieval = ScoredEpisodicRetrieval(store)
        result = await retrieval.retrieve("cat", user_id="u2")
        assert result == []

    async def test_excludes_deleted_memories(self, store: InMemoryEpisodicStore) -> None:
        store._memories.append(make_memory(deleted=True))
        retrieval = ScoredEpisodicRetrieval(store)
        result = await retrieval.retrieve("cat")
        assert result == []

    async def test_returns_empty_when_zero_lexical_and_vector_score(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(content="completely unrelated text"))
        retrieval = ScoredEpisodicRetrieval(store)
        result = await retrieval.retrieve("xyz")
        assert result == []


class TestLexicalScoring:
    async def test_keyword_overlap_ranks_higher_match_first(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(memory_id="low", content="cat"))
        store._memories.append(make_memory(memory_id="high", content="cat sat mat"))
        retrieval = ScoredEpisodicRetrieval(store)
        result = await retrieval.retrieve("cat sat mat")
        assert [m.memory_id for m in result] == ["high", "low"]

    async def test_weight_scales_score_higher_weight_wins_tie_lexical_score(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(memory_id="light", content="cat", weight=0.1))
        store._memories.append(make_memory(memory_id="heavy", content="cat", weight=0.9))
        retrieval = ScoredEpisodicRetrieval(store)
        result = await retrieval.retrieve("cat")
        assert [m.memory_id for m in result] == ["heavy", "light"]

    async def test_limit_truncates_results(self, store: InMemoryEpisodicStore) -> None:
        for i in range(5):
            store._memories.append(make_memory(memory_id=f"m{i}", content="cat"))
        retrieval = ScoredEpisodicRetrieval(store)
        result = await retrieval.retrieve("cat", limit=2)
        assert len(result) == 2


class TestVectorScoring:
    async def test_vector_similarity_added_to_score_when_embeddings_available(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(memory_id="m1", content="alpha"))
        embeddings = _StubEmbeddingClient(
            {"alpha query": [1.0, 0.0, 0.0], "alpha": [1.0, 0.0, 0.0]}
        )
        retrieval = ScoredEpisodicRetrieval(store, embedding_client=embeddings)
        result = await retrieval.retrieve("alpha query")
        assert len(result) == 1
        assert "alpha query" in embeddings.calls
        assert "alpha" in embeddings.calls

    async def test_falls_back_to_keyword_only_when_query_embedding_is_all_zero(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(memory_id="m1", content="cat sat"))
        embeddings = _StubEmbeddingClient({"cat sat": [0.0, 0.0, 0.0]})
        retrieval = ScoredEpisodicRetrieval(store, embedding_client=embeddings)
        result = await retrieval.retrieve("cat sat")
        assert len(result) == 1
        # Only the query embed call happens; per-memory embed is skipped since query_vec is None.
        assert embeddings.calls == ["cat sat"]

    async def test_falls_back_to_keyword_only_when_query_embedding_raises(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(memory_id="m1", content="cat sat"))
        embeddings = _StubEmbeddingClient({})
        embeddings.fail_on.add("cat sat")
        retrieval = ScoredEpisodicRetrieval(store, embedding_client=embeddings)
        result = await retrieval.retrieve("cat sat")
        assert len(result) == 1

    async def test_per_memory_vector_defaults_to_zero_when_embed_raises(
        self, store: InMemoryEpisodicStore
    ) -> None:
        store._memories.append(make_memory(memory_id="m1", content="cat sat"))
        embeddings = _StubEmbeddingClient({"cat sat query": [1.0, 0.0, 0.0]})
        embeddings.fail_on.add("cat sat")
        retrieval = ScoredEpisodicRetrieval(store, embedding_client=embeddings)
        result = await retrieval.retrieve("cat sat query")
        # Lexical overlap ("cat" "sat") still produces a positive score even though
        # the per-memory embed call raised and contributed 0.0 vector similarity.
        assert len(result) == 1


class TestKeywordSimilarityHelper:
    """The lexical term moved to `ranking.keyword_overlap` (#622).

    It was a private static method here while `InMemoryEpisodicStore.retrieve`
    computed a different lexical term inline, so "the" ranking was two rankings.
    Same three cases, asked of the one implementation.
    """

    def test_empty_query_words_returns_zero(self) -> None:
        assert keyword_overlap("", make_memory(content="some content")) == 0.0

    def test_empty_content_returns_zero(self) -> None:
        assert keyword_overlap("cat", make_memory(content="")) == 0.0

    def test_partial_overlap_ratio(self) -> None:
        assert keyword_overlap("cat dog bird", make_memory(content="the cat ran")) == pytest.approx(
            1 / 3
        )
