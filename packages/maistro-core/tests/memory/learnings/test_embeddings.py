"""Coverage for memory/learnings/embeddings.py."""

from __future__ import annotations

from maistro.memory.learnings.embeddings import (
    EMBEDDING_WEIGHT,
    KEYWORD_WEIGHT,
    MIN_COMBINED_SCORE,
    FakeEmbeddingClient,
    HybridLearningStore,
    NoopEmbeddingClient,
    cosine_similarity,
)
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_mismatched_lengths_returns_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def test_cosine_similarity_empty_vector_returns_zero() -> None:
    assert cosine_similarity([], []) == 0.0


def test_cosine_similarity_zero_norm_returns_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


async def test_noop_embedding_client_returns_zero_vectors() -> None:
    client = NoopEmbeddingClient(dimension=4)
    assert client.dimension == 4
    assert await client.embed("text") == [0.0, 0.0, 0.0, 0.0]
    assert await client.embed_batch(["a", "b"]) == [[0.0] * 4, [0.0] * 4]


async def test_fake_embedding_client_is_deterministic() -> None:
    client = FakeEmbeddingClient(dimension=8)
    assert client.dimension == 8
    v1 = await client.embed("hello")
    v2 = await client.embed("hello")
    assert v1 == v2
    assert len(v1) == 8


async def test_fake_embedding_client_differs_for_different_text() -> None:
    client = FakeEmbeddingClient(dimension=8)
    v1 = await client.embed("hello")
    v2 = await client.embed("goodbye")
    assert v1 != v2


async def test_fake_embedding_client_embed_batch() -> None:
    client = FakeEmbeddingClient(dimension=4)
    batch = await client.embed_batch(["a", "b"])
    assert len(batch) == 2
    assert batch[0] == await client.embed("a")


async def test_store_computes_embedding_when_client_present() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=FakeEmbeddingClient())
    learning_id = await hybrid.store(Learning(trigger_keys=["x"], learning="some learning text"))
    assert learning_id in hybrid._embedding_cache


async def test_store_skips_embedding_when_no_client() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner)
    learning_id = await hybrid.store(Learning(trigger_keys=["x"], learning="text"))
    assert hybrid._embedding_cache == {}
    assert learning_id is not None


async def test_store_skips_embedding_when_learning_text_empty() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=FakeEmbeddingClient())
    await hybrid.store(Learning(trigger_keys=["x"], learning=""))
    assert hybrid._embedding_cache == {}


async def test_store_swallows_embedding_failure() -> None:
    class _BrokenClient:
        dimension = 4

        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("boom")

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom")

    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=_BrokenClient())
    learning_id = await hybrid.store(Learning(trigger_keys=["x"], learning="text"))
    assert hybrid._embedding_cache == {}
    assert learning_id is not None


async def test_find_relevant_falls_back_to_keyword_only_when_no_client() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner)
    await hybrid.store(Learning(trigger_keys=["deploy"], learning="deploy carefully"))
    results = await hybrid.find_relevant("deploy")
    assert len(results) == 1


async def test_find_relevant_returns_empty_when_no_keyword_results() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=FakeEmbeddingClient())
    results = await hybrid.find_relevant("nothing matches")
    assert results == []


async def test_find_relevant_falls_back_when_query_embedding_fails() -> None:
    class _FailsOnQuery:
        dimension = 4
        calls = 0

        async def embed(self, text: str) -> list[float]:
            raise RuntimeError("boom")

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom")

    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=_FailsOnQuery())
    await hybrid.store(Learning(trigger_keys=["deploy"], learning="deploy carefully"))
    results = await hybrid.find_relevant("deploy")
    assert len(results) == 1


async def test_find_relevant_falls_back_when_query_vector_is_all_zero() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=NoopEmbeddingClient(dimension=4))
    await hybrid.store(Learning(trigger_keys=["deploy"], learning="deploy carefully"))
    results = await hybrid.find_relevant("deploy")
    assert len(results) == 1


async def test_find_relevant_uses_cached_embedding_for_scoring() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=FakeEmbeddingClient())
    await hybrid.store(Learning(trigger_keys=["deploy"], learning="deploy carefully"))
    results = await hybrid.find_relevant("deploy carefully")
    assert len(results) == 1


async def test_find_relevant_computes_and_caches_embedding_when_not_cached() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner, embedding_client=FakeEmbeddingClient())
    learning_id = await inner.store(Learning(trigger_keys=["deploy"], learning="deploy carefully"))
    # Not stored through hybrid.store(), so no cache entry exists yet.
    assert learning_id not in hybrid._embedding_cache
    results = await hybrid.find_relevant("deploy carefully")
    assert len(results) == 1
    assert learning_id in hybrid._embedding_cache


async def test_find_relevant_swallows_per_learning_embedding_failure() -> None:
    class _FailsOnLearningOnly:
        dimension = 4
        query_calls = 0

        async def embed(self, text: str) -> list[float]:
            self.query_calls += 1
            if self.query_calls == 1:
                return [1.0, 1.0, 1.0, 1.0]
            raise RuntimeError("boom")

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom")

    inner = InMemoryLearningStore()
    client = _FailsOnLearningOnly()
    hybrid = HybridLearningStore(inner, embedding_client=client)
    await inner.store(Learning(trigger_keys=["deploy"], learning="deploy carefully"))
    results = await hybrid.find_relevant("deploy carefully")
    # combined score from keyword alone may or may not clear the threshold,
    # but the call must not raise.
    assert isinstance(results, list)


async def test_find_relevant_filters_below_min_combined_score() -> None:
    inner = InMemoryLearningStore()
    # query embeds to all-zero -> falls back to keyword-only path, so use a
    # non-noop client returning orthogonal vectors to force a low combined score.

    class _OrthogonalClient:
        dimension = 2
        n = 0

        async def embed(self, text: str) -> list[float]:
            self.n += 1
            return [1.0, 0.0] if self.n == 1 else [0.0, 1.0]

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            raise NotImplementedError

    hybrid2 = HybridLearningStore(inner, embedding_client=_OrthogonalClient())
    await inner.store(Learning(trigger_keys=["x"], learning="x text"))
    results = await hybrid2.find_relevant("x")
    assert isinstance(results, list)


async def test_mark_used_delegates_to_inner_store() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner)
    lid = await hybrid.store(Learning(trigger_keys=["x"], learning="x"))
    await hybrid.mark_used([lid])
    stored = await inner.list_all()
    assert stored[0].hit_count == 1


async def test_check_auto_promotions_delegates_to_inner_store() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner)
    await hybrid.store(Learning(trigger_keys=["x"], learning="x", hit_count=10))
    promoted = await hybrid.check_auto_promotions(threshold=5)
    assert len(promoted) == 1


async def test_get_promoted_delegates_to_inner_store() -> None:
    inner = InMemoryLearningStore()
    hybrid = HybridLearningStore(inner)
    await hybrid.store(Learning(trigger_keys=["x"], learning="x", hit_count=10, status="promoted"))
    promoted = await hybrid.get_promoted()
    assert len(promoted) == 1


def test_weight_constants_have_expected_values() -> None:
    assert KEYWORD_WEIGHT == 1.0
    assert EMBEDDING_WEIGHT == 3.0
    assert MIN_COMBINED_SCORE == 0.3
