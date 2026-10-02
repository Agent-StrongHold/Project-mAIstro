"""Canonical Goal domain (#1572, `INTEROP_ONTOLOGY_V1` owner `maistro.goals`).

A Goal is durable desired-outcome and accountability state. It is not a Run
lifecycle: one Goal may require zero, one, or many Runs over its life, and a
Run's outcome is evidence for the next reconciliation decision rather than a
Goal transition. The interop contract fixes the shape this module owns --
`goal_id` identity, `goal_revision` revisioning, Project parent, exactly-one
owning Agent, zero-or-one parent Goal -- so the relationships below are the
contract's, not this module's invention.

What a Goal *is* lives here. What should happen next about it is #805, and the
durable wakeups that drive those decisions are #806; neither may define a
second Goal lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _id() -> str:
    return uuid.uuid4().hex


class GoalState(StrEnum):
    """Lifecycle of a Goal, not of the Runs it may select.

    ``SUPERSEDED`` is terminal and distinct from ``CANCELLED``: it records a
    Goal replaced by another rather than abandoned, which a reconciler must be
    able to tell apart when it walks lineage for prior evidence.
    """

    ACTIVE = "active"
    SATISFIED = "satisfied"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUPERSEDED = "superseded"


#: Terminal states are final: no transition leaves them, including to each
#: other. A Goal that needs to live again is a new Goal whose lineage names
#: this one, which keeps the historical record of why this one stopped.
TERMINAL_GOAL_STATES: frozenset[GoalState] = frozenset(
    {
        GoalState.SATISFIED,
        GoalState.CANCELLED,
        GoalState.FAILED,
        GoalState.SUPERSEDED,
    }
)


class GoalRevision(BaseModel):
    """One immutable statement of what a Goal wants and when it stops.

    Append-only. A Goal's wording, success conditions and stop conditions all
    change by adding a revision and moving the Goal's pointer, never by
    rewriting one: a Run that has already executed keeps the revision it was
    admitted against, so "what were we trying to do when this ran" stays
    answerable after the Goal has moved on.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_revision: str = Field(default_factory=_id)
    goal_id: str
    #: Append-only ordering within one Goal, starting at 1. Separate from the
    #: id so a reader can tell which of two revisions is newer without a
    #: timestamp comparison that two writers in the same millisecond lose.
    sequence: int = Field(ge=1)
    desired_state: str
    #: What makes this Goal satisfied. Evaluated by #805 against canonical
    #: evidence; this module stores them and judges none of them.
    success_conditions: list[str] = Field(default_factory=list)
    #: What makes this Goal stop without being satisfied.
    stop_conditions: list[str] = Field(default_factory=list)
    author_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("goal_revision", "goal_id", "desired_state", "author_id")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class Goal(BaseModel):
    """Durable desired outcome, owned by exactly one Agent in one Project."""

    model_config = ConfigDict(extra="forbid")

    goal_id: str = Field(default_factory=_id)
    workspace_id: str
    #: `project_goal` in the interop contract: exactly-one Project per Goal.
    project_id: str
    #: `agent_goal_ownership`: exactly-one accountable Agent. Changing it is an
    #: explicit recorded transition, never a side effect of execution.
    owner_agent_id: str
    #: `goal_subgoal`: zero-or-one parent. A Subgoal keeps its parent's Project.
    parent_goal_id: str | None = None
    state: GoalState = GoalState.ACTIVE
    #: Pointer into this Goal's append-only revisions. Explicit rather than
    #: "the newest row", so a reader never races a concurrent revision.
    current_revision: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("goal_id", "workspace_id", "project_id", "owner_agent_id", "current_revision")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("parent_goal_id")
    @classmethod
    def _parent_non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("parent_goal_id must be a non-empty string when set")
        return value

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_GOAL_STATES


class GoalNotFound(LookupError):
    """No Goal with this id is visible to the caller.

    A Goal in another Workspace raises this rather than a denial: a caller who
    cannot see a Goal must not learn that it exists (#1150).
    """


class GoalRevisionConflict(RuntimeError):
    """A write lost a compare-and-set against the Goal's current revision."""


class GoalStateConflict(RuntimeError):
    """A transition out of a terminal state, or from a stale state."""


class GoalLineageError(ValueError):
    """A Subgoal parent that does not exist, crosses a Project, or cycles."""


__all__ = [
    "TERMINAL_GOAL_STATES",
    "Goal",
    "GoalLineageError",
    "GoalNotFound",
    "GoalRevision",
    "GoalRevisionConflict",
    "GoalState",
    "GoalStateConflict",
]
