"""Tests for hybrid BM25 + vector retrieval ranking (SPEC-243 / ADR-080 part D)."""

from __future__ import annotations

from maistro.memory.episodic.ranking import rank, score
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier


def _mem(memory_id: str, weight: float) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        tier=MemoryTier.OBSERVATION,
        weight=weight,
        content="content",
        scope=MemoryScope.AGENT,
        agent_id="agent-1",
    )


def test_score_is_sum_of_lexical_and_vector_times_weight() -> None:
    mem = _mem("m1", weight=0.5)

    result = score("q", mem, lexical_fn=lambda q, m: 0.4, vector_fn=lambda q, m: 0.2)

    assert result == (0.4 + 0.2) * 0.5


def test_score_is_zero_for_zero_weight_regardless_of_relevance() -> None:
    mem = _mem("m1", weight=0.0)

    result = score("q", mem, lexical_fn=lambda q, m: 1.0, vector_fn=lambda q, m: 1.0)

    assert result == 0.0


def test_rank_sorts_descending_and_truncates_to_k() -> None:
    memories = [_mem("low", weight=0.1), _mem("high", weight=0.9), _mem("mid", weight=0.5)]

    ranked = rank(
        "q",
        memories,
        k=2,
        lexical_fn=lambda q, m: 0.5,
        vector_fn=lambda q, m: 0.0,
    )

    assert [m.memory_id for m in ranked] == ["high", "mid"]


def test_wisdom_tier_outranks_observation_tier_at_equal_relevance() -> None:
    wisdom = _mem("wisdom", weight=0.9)
    observation = _mem("observation", weight=0.3)

    ranked = rank(
        "q",
        [observation, wisdom],
        k=2,
        lexical_fn=lambda q, m: 0.5,
        vector_fn=lambda q, m: 0.5,
    )

    assert ranked[0].memory_id == "wisdom"
