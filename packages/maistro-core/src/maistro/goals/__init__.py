"""The canonical Goal store (`maistro.goals`, #1572).

Ontology owner of the shared ``Goal`` concept (`INTEROP_ONTOLOGY_V1`):
`Goal`, its append-only `GoalRevision` chain, Subgoal lineage through
``parent_goal_id``, and the recorded lifecycle/ownership transitions. One
:class:`GoalStore` protocol with an in-memory reference and SQLite and
PostgreSQL twins; principal-carrying access through
:class:`ScopedGoalStore` over the canonical Workspace authorization seam.
"""

from maistro.goals.authorization import GoalNotVisible, ScopedGoalStore
from maistro.goals.model import (
    TERMINAL_GOAL_STATUSES,
    Goal,
    GoalNotFound,
    GoalParentInvalid,
    GoalRevision,
    GoalRevisionConflict,
    GoalRevisionDraft,
    GoalStatus,
    GoalTransitionError,
    GoalTransitionKind,
    GoalTransitionRecord,
)
from maistro.goals.store import GoalStore, InMemoryGoalStore

__all__ = [
    "TERMINAL_GOAL_STATUSES",
    "Goal",
    "GoalNotFound",
    "GoalNotVisible",
    "GoalParentInvalid",
    "GoalRevision",
    "GoalRevisionConflict",
    "GoalRevisionDraft",
    "GoalStatus",
    "GoalStore",
    "GoalTransitionError",
    "GoalTransitionKind",
    "GoalTransitionRecord",
    "InMemoryGoalStore",
    "ScopedGoalStore",
]
