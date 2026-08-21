"""Memory types: Learning, EpisodicMemory, Outcome, tiers, scopes (ADR-013).

Single source of truth lives in :mod:`maistro.types.memory`. This module used to
carry a divergent, shorter copy of these dataclasses (missing rca_category,
rca_prevention, success_after_use, failure_after_use, charged_microchips,
pricing_version). Concrete stores/extractors imported from here while protocols
and persistence imported from maistro.types.memory, which caused AttributeError
and TypeError at runtime. It now re-exports the canonical (full) definitions so
every Learning/Outcome/EpisodicMemory usage resolves to the same class.
"""

from __future__ import annotations

from maistro.types.memory import (
    CONTRADICT_DELTA,
    INHERITANCE_PRIORITY,
    REINFORCE_DELTA,
    SCOPE_RANK,
    WEIGHT_BOUNDS,
    DecaySweep,
    EpisodicMemory,
    Learning,
    MemoryScope,
    MemoryTier,
    Outcome,
    SkillMutation,
)

__all__ = [
    "CONTRADICT_DELTA",
    "INHERITANCE_PRIORITY",
    "REINFORCE_DELTA",
    "SCOPE_RANK",
    "WEIGHT_BOUNDS",
    "DecaySweep",
    "EpisodicMemory",
    "Learning",
    "MemoryScope",
    "MemoryTier",
    "Outcome",
    "SkillMutation",
]
