"""Canonical Goal substrate (#1572): the owner `INTEROP_ONTOLOGY_V1` names for Goal."""

from __future__ import annotations

from maistro.goals.service import GoalService
from maistro.goals.store import GoalStore, InMemoryGoalStore
from maistro.goals.types import (
    Goal,
    GoalLineageError,
    GoalNotFound,
    GoalRevision,
    GoalRevisionConflict,
    GoalState,
    GoalTransitionRefused,
)

__all__ = [
    "Goal",
    "GoalLineageError",
    "GoalNotFound",
    "GoalRevision",
    "GoalRevisionConflict",
    "GoalService",
    "GoalState",
    "GoalStore",
    "GoalTransitionRefused",
    "InMemoryGoalStore",
]
