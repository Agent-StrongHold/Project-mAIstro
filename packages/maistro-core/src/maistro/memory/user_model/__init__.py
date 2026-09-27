"""Durable, user-owned user model built from consolidated memory (#1047)."""

from __future__ import annotations

from maistro.memory.user_model.promotion import correct_fact, forget_fact, promote_evidence
from maistro.memory.user_model.store import InMemoryUserModelStore
from maistro.memory.user_model.types import (
    Correction,
    CrossUserPromotionError,
    EvidenceRef,
    FactSensitivity,
    FactState,
    PromotionRefusedError,
    RevisionConflictError,
    StaleEvidenceError,
    TombstonedLineageError,
    UserModelError,
    UserModelFact,
    fact_key,
)

__all__ = [
    "Correction",
    "CrossUserPromotionError",
    "EvidenceRef",
    "FactSensitivity",
    "FactState",
    "InMemoryUserModelStore",
    "PromotionRefusedError",
    "RevisionConflictError",
    "StaleEvidenceError",
    "TombstonedLineageError",
    "UserModelError",
    "UserModelFact",
    "correct_fact",
    "fact_key",
    "forget_fact",
    "promote_evidence",
]
