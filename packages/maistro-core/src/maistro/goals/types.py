"""Canonical Goal records (#1572).

A Goal is the durable statement of what a Project is trying to reach, owned
by exactly one accountable Agent. What the Goal asks for lives in its
revisions, which are append-only: `Goal.current_revision` is an explicit
pointer at the latest one, so a Run bound to revision N keeps meaning what it
meant when it was admitted.

A change of owning Agent is recorded as a revision that repeats the previous
revision's content under the new owner. That keeps the previous owner in the
revision history and puts the reassignment under the same compare-and-set as
every other revision, without a third table for one kind of event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class GoalState(StrEnum):
    ACTIVE = "active"
    SATISFIED = "satisfied"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUPERSEDED = "superseded"

    @property
    def is_terminal(self) -> bool:
        return self is not GoalState.ACTIVE


@dataclass(frozen=True)
class Goal:
    goal_id: str
    workspace_id: str
    project_id: str
    owner_agent_id: str
    parent_goal_id: str | None
    state: GoalState
    current_revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class GoalRevision:
    goal_id: str
    revision: int
    owner_agent_id: str
    desired_state: str
    success_conditions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    author_principal_id: str
    created_at: datetime


class GoalNotFound(KeyError):
    """No Goal with this id, or none the principal may see; never which."""


class GoalRevisionConflict(ValueError):
    """The Goal moved on since the caller read it: stale revision or state."""


class GoalTransitionRefused(ValueError):
    """The Goal is terminal, or the requested transition is not a transition."""


class GoalLineageError(ValueError):
    """The Project is not in the Workspace, or the parent Goal is not in the Project."""


__all__ = [
    "Goal",
    "GoalLineageError",
    "GoalNotFound",
    "GoalRevision",
    "GoalRevisionConflict",
    "GoalState",
    "GoalTransitionRefused",
]
