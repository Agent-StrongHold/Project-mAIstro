"""Tests for memory decay + reinforcement dynamics (SPEC-240 / ADR-080 part A)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.episodic.tiers import on_access, on_feedback, reclassify, tick_decay
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.types.memory import (
    DEFAULT_DECAY_RATE,
    REGRET_DEMOTE_THRESHOLD,
    WISDOM_PROMOTE_THRESHOLD,
)


def _mem(
    tier: MemoryTier = MemoryTier.OBSERVATION,
    weight: float = 0.3,
    reinforcement_count: int = 0,
    contradiction_count: int = 0,
    decay_rate: float = DEFAULT_DECAY_RATE,
    last_accessed_at: datetime | None = None,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id="m1",
        tier=tier,
        weight=weight,
        content="some content",
        org_id="org-1",
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        reinforcement_count=reinforcement_count,
        contradiction_count=contradiction_count,
        decay_rate=decay_rate,
        last_accessed_at=last_accessed_at or datetime.now(UTC) - timedelta(hours=10),
    )


class TestOnAccess:
    def test_refreshes_last_accessed_at(self) -> None:
        old = datetime.now(UTC) - timedelta(hours=5)
        mem = _mem(last_accessed_at=old)
        now = datetime.now(UTC)
        refreshed = on_access(mem, now=now)
        assert refreshed.last_accessed_at == now

    def test_leaves_weight_and_tier_unchanged(self) -> None:
        mem = _mem(weight=0.4, tier=MemoryTier.LESSON)
        refreshed = on_access(mem)
        assert refreshed.weight == pytest.approx(0.4)
        assert refreshed.tier == MemoryTier.LESSON


class TestOnFeedback:
    def test_up_increases_weight(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, weight=0.6)
        result = on_feedback(mem, "up")
        assert result.weight > mem.weight

    def test_up_slows_decay_rate(self) -> None:
        mem = _mem(decay_rate=DEFAULT_DECAY_RATE)
        result = on_feedback(mem, "up")
        assert result.decay_rate < mem.decay_rate

    def test_down_decreases_weight(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, weight=0.7)
        result = on_feedback(mem, "down")
        assert result.weight < mem.weight

    def test_down_speeds_decay_rate(self) -> None:
        mem = _mem(decay_rate=DEFAULT_DECAY_RATE)
        result = on_feedback(mem, "down")
        assert result.decay_rate > mem.decay_rate

    def test_up_respects_tier_ceiling(self) -> None:
        mem = _mem(tier=MemoryTier.OBSERVATION, weight=0.49)
        result = on_feedback(mem, "up")
        assert result.weight <= 0.5

    def test_down_respects_tier_floor(self) -> None:
        mem = _mem(tier=MemoryTier.REGRET, weight=0.61)
        result = on_feedback(mem, "down")
        assert result.weight >= 0.6

    def test_up_increments_reinforcement_count(self) -> None:
        mem = _mem(reinforcement_count=2)
        result = on_feedback(mem, "up")
        assert result.reinforcement_count == 3

    def test_down_increments_contradiction_count(self) -> None:
        mem = _mem(contradiction_count=1)
        result = on_feedback(mem, "down")
        assert result.contradiction_count == 2

    def test_promotes_to_wisdom_after_threshold(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, reinforcement_count=WISDOM_PROMOTE_THRESHOLD - 1)
        result = on_feedback(mem, "up")
        assert result.tier == MemoryTier.WISDOM

    def test_demotes_to_regret_after_threshold(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, contradiction_count=REGRET_DEMOTE_THRESHOLD - 1)
        result = on_feedback(mem, "down")
        assert result.tier == MemoryTier.REGRET


class TestReclassify:
    def test_returns_current_tier_below_thresholds(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, reinforcement_count=1, contradiction_count=1)
        assert reclassify(mem) == MemoryTier.LESSON

    def test_promotes_to_wisdom_at_threshold(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, reinforcement_count=WISDOM_PROMOTE_THRESHOLD)
        assert reclassify(mem) == MemoryTier.WISDOM

    def test_demotes_to_regret_at_threshold(self) -> None:
        mem = _mem(tier=MemoryTier.LESSON, contradiction_count=REGRET_DEMOTE_THRESHOLD)
        assert reclassify(mem) == MemoryTier.REGRET


class TestTickDecay:
    def test_reduces_weight_over_elapsed_time(self) -> None:
        old = datetime.now(UTC) - timedelta(hours=10)
        mem = _mem(tier=MemoryTier.LESSON, weight=0.8, last_accessed_at=old, decay_rate=0.01)
        now = datetime.now(UTC)
        decayed = tick_decay(mem, now=now)
        assert decayed.weight < mem.weight

    def test_no_decay_with_zero_elapsed_time(self) -> None:
        now = datetime.now(UTC)
        mem = _mem(tier=MemoryTier.LESSON, weight=0.8, last_accessed_at=now)
        decayed = tick_decay(mem, now=now)
        assert decayed.weight == pytest.approx(mem.weight)

    def test_never_decays_below_regret_floor(self) -> None:
        old = datetime.now(UTC) - timedelta(hours=10_000)
        mem = _mem(tier=MemoryTier.REGRET, weight=0.65, last_accessed_at=old, decay_rate=1.0)
        decayed = tick_decay(mem, now=datetime.now(UTC))
        assert decayed.weight >= 0.6

    def test_never_decays_below_wisdom_floor(self) -> None:
        old = datetime.now(UTC) - timedelta(hours=10_000)
        mem = _mem(tier=MemoryTier.WISDOM, weight=0.95, last_accessed_at=old, decay_rate=1.0)
        decayed = tick_decay(mem, now=datetime.now(UTC))
        assert decayed.weight >= 0.9

    def test_repeated_ticks_hold_at_floor(self) -> None:
        mem = _mem(tier=MemoryTier.WISDOM, weight=0.9, decay_rate=1.0)
        now = datetime.now(UTC)
        for i in range(1, 50):
            mem = tick_decay(mem, now=now + timedelta(hours=i * 1000))
        assert mem.weight >= 0.9
