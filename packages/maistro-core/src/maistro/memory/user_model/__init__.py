"""Durable, user-owned user model built from consolidated memory (#1047)."""

from __future__ import annotations

from maistro.memory.user_model.pg_store import (
    PostgresUserModelStore,
    UserModelFactRow,
    UserModelStatementKeyRow,
)
from maistro.memory.user_model.promotion import correct_fact, forget_fact, promote_evidence
from maistro.memory.user_model.retrieval import RecallQuery, ScoredFact, recall, score_fact
from maistro.memory.user_model.service import UserModelService
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
    "PostgresUserModelStore",
    "PromotionRefusedError",
    "RecallQuery",
    "RevisionConflictError",
    "ScoredFact",
    "StaleEvidenceError",
    "TombstonedLineageError",
    "UserModelError",
    "UserModelFact",
    "UserModelFactRow",
    "UserModelService",
    "UserModelStatementKeyRow",
    "correct_fact",
    "fact_key",
    "forget_fact",
    "promote_evidence",
    "recall",
    "score_fact",
]
