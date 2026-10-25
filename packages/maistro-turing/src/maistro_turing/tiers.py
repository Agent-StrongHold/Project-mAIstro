"""Weight bounds and inheritance priority per tier. See specs/tiers.md.

``clamp_weight`` is the documented numeric safeguard for every tiered memory
write. #859 puts it on the actual write path: the Turing memory bridge clamps
at its single ``store_episode`` seam, so a caller cannot persist a weight
outside its tier's declared bounds (or a non-finite one) anywhere.
"""

from __future__ import annotations

import math

from .types import MemoryTier

WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]] = {
    MemoryTier.OBSERVATION: (0.1, 0.5),
    MemoryTier.HYPOTHESIS: (0.2, 0.6),
    MemoryTier.OPINION: (0.3, 0.8),
    MemoryTier.LESSON: (0.5, 0.9),
    MemoryTier.REGRET: (0.6, 1.0),
    MemoryTier.ACCOMPLISHMENT: (0.6, 1.0),
    MemoryTier.AFFIRMATION: (0.6, 1.0),
    MemoryTier.WISDOM: (0.9, 1.0),
}


INHERITANCE_PRIORITY: dict[MemoryTier, int] = {
    MemoryTier.OBSERVATION: 1,
    MemoryTier.HYPOTHESIS: 2,
    MemoryTier.OPINION: 3,
    MemoryTier.LESSON: 4,
    MemoryTier.REGRET: 5,
    MemoryTier.ACCOMPLISHMENT: 5,
    MemoryTier.AFFIRMATION: 5,
    MemoryTier.WISDOM: 6,
}


def clamp_weight(tier: MemoryTier, proposed: float) -> float:
    """Clamp one proposed weight into its tier's declared bounds.

    NaN and infinities are refused rather than clamped: ``max``/``min`` with a
    NaN operand returns an arbitrary endpoint, which would silently launder a
    malformed weight into a plausible-looking one instead of failing the write.
    """
    weight = float(proposed)
    if not math.isfinite(weight):
        raise ValueError(f"weight must be a finite number, got {proposed!r}")
    lo, hi = WEIGHT_BOUNDS[tier]
    return max(lo, min(hi, weight))
