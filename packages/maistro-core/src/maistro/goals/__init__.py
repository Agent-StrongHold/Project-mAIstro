"""Canonical Goal substrate (`maistro.goals`, #1572).

`INTEROP_ONTOLOGY_V1` names this package the owner of the Goal concept. Until
now nothing implemented it: every Goal-consuming issue declared that it only
*consumes* the store, so no issue would ever build it, and `goal_id` /
`goal_revision` fields elsewhere pointed at nothing.

What a Goal is lives here. What should happen next about one is #805, and the
durable wakeups that drive those decisions are #806. Neither may define a
second Goal lifecycle, and physical execution stays Graph -> Run -> NodeRun ->
Attempt.
"""

from __future__ import annotations

from maistro.goals.store import GoalStore, InMemoryGoalStore
from maistro.goals.types import (
    TERMINAL_GOAL_STATES,
    Goal,
    GoalLineageError,
    GoalNotFound,
    GoalRevision,
    GoalRevisionConflict,
    GoalState,
    GoalStateConflict,
)

__all__ = [
    "TERMINAL_GOAL_STATES",
    "Goal",
    "GoalLineageError",
    "GoalNotFound",
    "GoalRevision",
    "GoalRevisionConflict",
    "GoalState",
    "GoalStateConflict",
    "GoalStore",
    "InMemoryGoalStore",
]
