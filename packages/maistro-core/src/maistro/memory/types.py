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
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    ANTI_PATTERN_HALF_LIFE_DAYS,
    CONTRADICT_DELTA,
    DEFAULT_LEARNING_CONFIDENCE,
    EMPIRICAL_HALF_LIFE_DAYS,
    INHERITANCE_PRIORITY,
    LEARNING_STAGE_ORDER,
    REINFORCE_DELTA,
    SCOPE_RANK,
    VALIDATED_CONFIDENCE_FLOOR,
    WEIGHT_BOUNDS,
    DecaySweep,
    EpisodicMemory,
    EpistemicType,
    Learning,
    LearningStage,
    MemoryScope,
    MemoryTier,
    Outcome,
    SkillMutation,
)

__all__ = [
    "ANTI_PATTERN_CONFIDENCE_FLOOR",
    "ANTI_PATTERN_HALF_LIFE_DAYS",
    "CONTRADICT_DELTA",
    "DEFAULT_LEARNING_CONFIDENCE",
    "EMPIRICAL_HALF_LIFE_DAYS",
    "INHERITANCE_PRIORITY",
    "LEARNING_STAGE_ORDER",
    "REINFORCE_DELTA",
    "SCOPE_RANK",
    "VALIDATED_CONFIDENCE_FLOOR",
    "WEIGHT_BOUNDS",
    "DecaySweep",
    "EpisodicMemory",
    "EpistemicType",
    "Learning",
    "LearningStage",
    "MemoryScope",
    "MemoryTier",
    "Outcome",
    "SkillMutation",
]
