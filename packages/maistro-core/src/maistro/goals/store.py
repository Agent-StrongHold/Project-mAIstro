"""The canonical Goal store protocol and its in-memory implementation (#1572).

Every method is Workspace-scoped. A Goal in another Workspace raises
`GoalNotFound` rather than a denial, so a caller cannot probe for the existence
of work it may not see (#1150): "not yours" and "not there" must be one answer
or the error itself leaks the roster.

Writes that depend on current state are compare-and-set. Revising a Goal names
the revision it believed current, and transitioning names the state it believed
current; a loser is refused rather than silently applied, because two
reconcilers deciding at once is the normal case for #805, not an edge one.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class GoalStore(Protocol):
    """Durable desired-outcome state. Decides nothing; records what is wanted."""

    async def create(self, goal: Goal, revision: GoalRevision) -> Goal:
        """Record a new Goal and the first revision it points at.

        The pair is written together: a Goal whose `current_revision` names a
        row that does not exist is unreadable, and a revision belonging to no
        Goal is unreachable. Raises `GoalLineageError` when `parent_goal_id`
        names a Goal that is missing, in another Project, or would cycle.
        """
        ...

    async def get(self, workspace_id: str, goal_id: str) -> Goal | None:
        """The Goal, or `None` when it is absent *or* in another Workspace."""
        ...

    async def revise(
        self, workspace_id: str, goal_id: str, *, expected_revision: str, revision: GoalRevision
    ) -> Goal:
        """Append a revision and move the pointer, if the pointer still matches.

        Raises `GoalRevisionConflict` when another writer moved it first, and
        `GoalStateConflict` on a terminal Goal: a finished Goal's statement of
        intent is part of the historical record.
        """
        ...

    async def transition(
        self, workspace_id: str, goal_id: str, *, expected_state: GoalState, state: GoalState
    ) -> Goal:
        """Move lifecycle state, if it still matches `expected_state`.

        Terminal states are final — including to each other — so a Goal that
        must live again is a new Goal whose lineage names this one.
        """
        ...

    async def reassign(
        self, workspace_id: str, goal_id: str, *, expected_agent_id: str, owner_agent_id: str
    ) -> Goal:
        """Hand accountability to another Agent, explicitly.

        Separate from `revise` because ownership is not part of what a Goal
        wants: moving it must not require restating the desired outcome, and
        restating the outcome must not quietly move it.
        """
        ...

    async def revisions(self, workspace_id: str, goal_id: str) -> list[GoalRevision]:
        """Every revision of this Goal, oldest first. Append-only."""
        ...

    async def revision(self, workspace_id: str, goal_revision: str) -> GoalRevision | None:
        """One revision by id, so a historical Run can read the exact text it ran against."""
        ...

    async def active_for_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        """The non-terminal Goals this Agent is accountable for.

        What a persistent Workspace Agent enumerates when it wakes with no chat
        session (#805 AC-1).
        """
        ...

    async def children(self, workspace_id: str, goal_id: str) -> list[Goal]:
        """Direct Subgoals, oldest first."""
        ...


def _assert_lineage(parent: Goal | None, goal: Goal) -> None:
    if goal.parent_goal_id is None:
        return
    if parent is None:
        raise GoalLineageError(f"parent Goal {goal.parent_goal_id!r} does not exist")
    if parent.project_id != goal.project_id:
        raise GoalLineageError(
            "a Subgoal keeps its parent's Project: "
            f"parent is in {parent.project_id!r}, child declares {goal.project_id!r}"
        )
    if parent.goal_id == goal.goal_id:
        raise GoalLineageError("a Goal cannot be its own Subgoal")


class InMemoryGoalStore:
    """Process-local Goal store, for tests and ephemeral composition.

    As durable as the process. Paired with a durable Run store it would record
    Runs against Goals that vanish on restart, so the Container selects it only
    when no durable substrate is configured.
    """

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}
        self._revisions: dict[str, list[GoalRevision]] = {}
        self._by_revision: dict[str, GoalRevision] = {}
        self._lock = asyncio.Lock()

    def _visible(self, workspace_id: str, goal_id: str) -> Goal | None:
        goal = self._goals.get(goal_id)
        if goal is None or goal.workspace_id != workspace_id:
            return None
        return goal

    def _require(self, workspace_id: str, goal_id: str) -> Goal:
        goal = self._visible(workspace_id, goal_id)
        if goal is None:
            raise GoalNotFound(f"Goal {goal_id!r} is not visible in this Workspace")
        return goal

    async def create(self, goal: Goal, revision: GoalRevision) -> Goal:
        if revision.goal_id != goal.goal_id:
            raise GoalLineageError("the first revision must belong to the Goal it opens")
        if revision.goal_revision != goal.current_revision:
            raise GoalRevisionConflict("a new Goal must point at the revision it is created with")
        async with self._lock:
            if goal.goal_id in self._goals:
                raise GoalRevisionConflict(f"Goal {goal.goal_id!r} already exists")
            parent = (
                self._visible(goal.workspace_id, goal.parent_goal_id)
                if goal.parent_goal_id
                else None
            )
            _assert_lineage(parent, goal)
            self._goals[goal.goal_id] = goal
            self._revisions[goal.goal_id] = [revision]
            self._by_revision[revision.goal_revision] = revision
            return goal

    async def get(self, workspace_id: str, goal_id: str) -> Goal | None:
        return self._visible(workspace_id, goal_id)

    async def revise(
        self, workspace_id: str, goal_id: str, *, expected_revision: str, revision: GoalRevision
    ) -> Goal:
        async with self._lock:
            goal = self._require(workspace_id, goal_id)
            if goal.is_terminal:
                raise GoalStateConflict(f"Goal {goal_id!r} is {goal.state} and cannot be revised")
            if goal.current_revision != expected_revision:
                raise GoalRevisionConflict(
                    f"Goal {goal_id!r} moved to {goal.current_revision!r} "
                    f"while {expected_revision!r} was held"
                )
            if revision.goal_id != goal_id:
                raise GoalLineageError("a revision must belong to the Goal it revises")
            history = self._revisions[goal_id]
            if revision.sequence != history[-1].sequence + 1:
                raise GoalRevisionConflict(
                    f"revision sequence must be {history[-1].sequence + 1}, got {revision.sequence}"
                )
            updated = goal.model_copy(
                update={
                    "current_revision": revision.goal_revision,
                    "updated_at": revision.created_at,
                }
            )
            history.append(revision)
            self._by_revision[revision.goal_revision] = revision
            self._goals[goal_id] = updated
            return updated

    async def transition(
        self, workspace_id: str, goal_id: str, *, expected_state: GoalState, state: GoalState
    ) -> Goal:
        async with self._lock:
            goal = self._require(workspace_id, goal_id)
            if goal.state in TERMINAL_GOAL_STATES:
                raise GoalStateConflict(
                    f"Goal {goal_id!r} is {goal.state}, which is terminal; "
                    "open a new Goal naming this one instead"
                )
            if goal.state != expected_state:
                raise GoalStateConflict(
                    f"Goal {goal_id!r} is {goal.state} while {expected_state} was held"
                )
            updated = goal.model_copy(update={"state": state, "updated_at": datetime.now(UTC)})
            self._goals[goal_id] = updated
            return updated

    async def reassign(
        self, workspace_id: str, goal_id: str, *, expected_agent_id: str, owner_agent_id: str
    ) -> Goal:
        async with self._lock:
            goal = self._require(workspace_id, goal_id)
            if goal.is_terminal:
                raise GoalStateConflict(
                    f"Goal {goal_id!r} is {goal.state} and cannot be reassigned"
                )
            if goal.owner_agent_id != expected_agent_id:
                raise GoalStateConflict(
                    f"Goal {goal_id!r} is owned by {goal.owner_agent_id!r} "
                    f"while {expected_agent_id!r} was held"
                )
            updated = goal.model_copy(
                update={"owner_agent_id": owner_agent_id, "updated_at": datetime.now(UTC)}
            )
            self._goals[goal_id] = updated
            return updated

    async def revisions(self, workspace_id: str, goal_id: str) -> list[GoalRevision]:
        self._require(workspace_id, goal_id)
        return list(self._revisions[goal_id])

    async def revision(self, workspace_id: str, goal_revision: str) -> GoalRevision | None:
        found = self._by_revision.get(goal_revision)
        if found is None or self._visible(workspace_id, found.goal_id) is None:
            return None
        return found

    async def active_for_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        return sorted(
            (
                goal
                for goal in self._goals.values()
                if goal.workspace_id == workspace_id
                and goal.owner_agent_id == agent_id
                and not goal.is_terminal
            ),
            key=lambda g: (g.created_at, g.goal_id),
        )

    async def children(self, workspace_id: str, goal_id: str) -> list[Goal]:
        self._require(workspace_id, goal_id)
        return sorted(
            (
                goal
                for goal in self._goals.values()
                if goal.workspace_id == workspace_id and goal.parent_goal_id == goal_id
            ),
            key=lambda g: (g.created_at, g.goal_id),
        )


__all__ = ["GoalStore", "InMemoryGoalStore"]
