"""Characterization tests for #2310's existing consolidation proposal seam.

These tests deliberately exercise pure proposal generation, not a canonical
Graph/NodeRun or durable store. Follow-up implementation must add the latter.
"""

from maistro.memory.episodic.consolidation import (
    apply_merge,
    consolidate,
)
from maistro.memory.types import EpisodicMemory, MemoryTier


def _memory(memory_id: str, content: str) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        tier=MemoryTier.OBSERVATION,
        content=content,
        weight=0.4,
    )


def test_consolidation_proposes_merge_without_mutating_originals() -> None:
    first = _memory("first", "Battery chemistry")
    second = _memory("second", "Battery chemistry")
    result = consolidate(
        [first, second],
        similarity_fn=lambda a, b: 1.0,
        contradiction_fn=lambda a, b: False,
    )

    assert len(result.merges) == 1
    assert result.contradictions == []
    assert result.merges[0].primary.memory_id == "first"
    assert [m.memory_id for m in result.merges[0].absorbed] == ["second"]
    assert first.deleted is False
    assert second.deleted is False

    updated_primary, absorbed = apply_merge(result.merges[0])
    assert updated_primary.memory_id == first.memory_id
    assert absorbed[0].deleted is True
    assert second.deleted is False


def test_contradiction_proposal_does_not_automatically_merge() -> None:
    first = _memory("first", "All swans are white")
    second = _memory("second", "Some swans are black")
    result = consolidate(
        [first, second],
        similarity_fn=lambda a, b: 1.0,
        contradiction_fn=lambda a, b: True,
    )

    assert result.merges == []
    assert len(result.contradictions) == 1
    assert result.contradictions[0].a.memory_id == "first"
    assert result.contradictions[0].b.memory_id == "second"
