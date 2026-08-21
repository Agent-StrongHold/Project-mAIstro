"""7-tier episodic memory with enforced weight bounds (ADR-016).

Decay + reinforcement dynamics (on_access/on_feedback/reclassify/tick_decay)
implement ADR-080 part A / SPEC-240.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Literal

from maistro.memory.types import (
    REINFORCE_DELTA,
    WEIGHT_BOUNDS,
    EpisodicMemory,
    MemoryTier,
)
from maistro.types.memory import (
    BOOST_RATE,
    DROP_RATE,
    FAST_DECAY,
    REGRET_DEMOTE_THRESHOLD,
    SLOW_DECAY,
    WISDOM_PROMOTE_THRESHOLD,
)


def clamp_weight(tier: MemoryTier, proposed: float) -> float:
    """Clamp weight to tier bounds."""
    lo, hi = WEIGHT_BOUNDS.get(tier, (0.1, 1.0))
    return max(lo, min(hi, proposed))


def reinforce(memory: EpisodicMemory, delta: float = REINFORCE_DELTA) -> EpisodicMemory:
    """Return a new EpisodicMemory with increased weight, clamped to tier ceiling."""
    return dataclasses.replace(
        memory,
        weight=clamp_weight(memory.tier, memory.weight + delta),
        reinforcement_count=memory.reinforcement_count + 1,
    )


def decay(memory: EpisodicMemory, delta: float = REINFORCE_DELTA) -> EpisodicMemory:
    """Return a new EpisodicMemory with decreased weight, clamped to tier floor."""
    return dataclasses.replace(
        memory,
        weight=clamp_weight(memory.tier, memory.weight - delta),
        contradiction_count=memory.contradiction_count + 1,
    )


def on_access(memory: EpisodicMemory, *, now: datetime | None = None) -> EpisodicMemory:
    """Refresh last_accessed_at; weight and tier are left unchanged."""
    return dataclasses.replace(memory, last_accessed_at=now or datetime.now(UTC))


def reclassify(memory: EpisodicMemory) -> MemoryTier:
    """Cumulative feedback promotes to WISDOM or demotes to REGRET past thresholds."""
    if memory.reinforcement_count >= WISDOM_PROMOTE_THRESHOLD:
        return MemoryTier.WISDOM
    if memory.contradiction_count >= REGRET_DEMOTE_THRESHOLD:
        return MemoryTier.REGRET
    return memory.tier


def on_feedback(memory: EpisodicMemory, signal: Literal["up", "down"]) -> EpisodicMemory:
    """Boost/slow on "up", drop/speed on "down"; reclassify tier afterward."""
    if signal == "up":
        updated = reinforce(memory, delta=REINFORCE_DELTA * BOOST_RATE)
        updated = dataclasses.replace(updated, decay_rate=updated.decay_rate * SLOW_DECAY)
    else:
        updated = decay(memory, delta=REINFORCE_DELTA * DROP_RATE)
        updated = dataclasses.replace(updated, decay_rate=updated.decay_rate * FAST_DECAY)

    new_tier = reclassify(updated)
    if new_tier != updated.tier:
        updated = dataclasses.replace(
            updated, tier=new_tier, weight=clamp_weight(new_tier, updated.weight)
        )
    return updated


def tick_decay(memory: EpisodicMemory, *, now: datetime | None = None) -> EpisodicMemory:
    """Apply time-based weight decay scaled by decay_rate and elapsed hours."""
    now = now or datetime.now(UTC)
    elapsed_hours = (now - memory.last_accessed_at).total_seconds() / 3600.0
    lost = memory.decay_rate * elapsed_hours
    return dataclasses.replace(
        memory,
        weight=clamp_weight(memory.tier, memory.weight - lost),
        last_accessed_at=now,
    )
