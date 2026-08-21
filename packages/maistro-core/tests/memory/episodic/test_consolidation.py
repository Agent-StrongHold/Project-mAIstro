"""Tests for memory consolidation (SPEC-241 / ADR-080 part B)."""

from __future__ import annotations

from maistro.memory.episodic.consolidation import (
    apply_contradiction,
    apply_merge,
    consolidate,
    consolidate_pair,
    run_batch,
)
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier


def _mem(memory_id: str, content: str, weight: float = 0.3) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        tier=MemoryTier.OBSERVATION,
        weight=weight,
        content=content,
        scope=MemoryScope.AGENT,
        agent_id="agent-1",
    )


def test_consolidate_merges_pairs_above_similarity_threshold() -> None:
    a = _mem("a", "the sky is blue", weight=0.4)
    b = _mem("b", "the sky is blue today", weight=0.6)

    result = consolidate(
        [a, b],
        similarity_fn=lambda x, y: 0.9,
        contradiction_fn=lambda x, y: False,
    )

    assert len(result.merges) == 1
    assert result.merges[0].primary.memory_id == "a"
    assert result.merges[0].absorbed[0].memory_id == "b"
    assert result.contradictions == []


def test_consolidate_flags_contradictions_instead_of_merging() -> None:
    a = _mem("a", "the sky is blue")
    b = _mem("b", "the sky is green")

    result = consolidate(
        [a, b],
        similarity_fn=lambda x, y: 0.95,
        contradiction_fn=lambda x, y: True,
    )

    assert result.merges == []
    assert len(result.contradictions) == 1
    assert result.contradictions[0].confidence_delta > 0


def test_consolidate_does_not_merge_or_flag_unrelated_memories() -> None:
    a = _mem("a", "the sky is blue")
    b = _mem("b", "the ocean is deep")

    result = consolidate(
        [a, b],
        similarity_fn=lambda x, y: 0.1,
        contradiction_fn=lambda x, y: False,
    )

    assert result.merges == []
    assert result.contradictions == []


def test_apply_merge_marks_absorbed_deleted_never_purged() -> None:
    a = _mem("a", "x", weight=0.4)
    b = _mem("b", "x", weight=0.6)

    result = consolidate(
        [a, b], similarity_fn=lambda x, y: 1.0, contradiction_fn=lambda x, y: False
    )
    primary, absorbed = apply_merge(result.merges[0])

    assert primary.memory_id == "a"
    assert primary.weight == result.merges[0].merged_weight
    assert absorbed[0].memory_id == "b"
    assert absorbed[0].deleted is True


def test_apply_contradiction_lowers_both_sides_and_flags_for_review() -> None:
    a = _mem("a", "x", weight=0.5)
    b = _mem("b", "y", weight=0.5)

    result = consolidate([a, b], similarity_fn=lambda x, y: 0.0, contradiction_fn=lambda x, y: True)
    new_a, new_b = apply_contradiction(result.contradictions[0])

    assert new_a.weight < a.weight
    assert new_b.weight < b.weight
    assert new_a.flagged_for_review is True
    assert new_b.flagged_for_review is True


def test_consolidate_pair_runs_immediate_trigger_for_single_pair() -> None:
    new_memory = _mem("new", "the sky is blue")
    existing = _mem("existing", "the sky is green")

    result = consolidate_pair(
        new_memory,
        existing,
        similarity_fn=lambda x, y: 0.0,
        contradiction_fn=lambda x, y: True,
    )

    assert len(result.contradictions) == 1


def test_run_batch_reports_merged_and_flagged_counts_and_applies_writes() -> None:
    a = _mem("a", "x", weight=0.4)
    b = _mem("b", "x", weight=0.6)
    c = _mem("c", "contradicts a")
    d = _mem("d", "contradicts b")

    applied_merges = []
    applied_contradictions = []

    def similarity_fn(x: EpisodicMemory, y: EpisodicMemory) -> float:
        return 1.0 if {x.memory_id, y.memory_id} == {"a", "b"} else 0.0

    def contradiction_fn(x: EpisodicMemory, y: EpisodicMemory) -> bool:
        return {x.memory_id, y.memory_id} == {"c", "d"}

    report = run_batch(
        [a, b, c, d],
        similarity_fn=similarity_fn,
        contradiction_fn=contradiction_fn,
        apply_store_merge=applied_merges.append,
        apply_store_contradiction=applied_contradictions.append,
    )

    assert report.merged == 1
    assert report.flagged == 1
    assert len(applied_merges) == 1
    assert len(applied_contradictions) == 1
