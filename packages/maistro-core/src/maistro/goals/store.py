"""The Goal store contract and its in-memory reference (#1572).

Every backend holds the same rules, read against one conformance suite:

* a Goal is created with revision 1 in one step, in a Project of its
  Workspace, and a Subgoal's parent is in the same Project;
* revisions are append-only and compare-and-set on `expected_revision`, so
  two writers holding the same revision produce exactly one winner;
* a state transition is compare-and-set on state and revision, and a terminal
  state is final: nothing revises, reassigns or transitions it afterwards.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.goals.types import (
    Goal,
    GoalLineageError,
    GoalNotFound,
    GoalRevision,
    GoalRevisionConflict,
    GoalState,
    GoalTransitionRefused,
)
from maistro.projects.scope_store import ProjectScopeStore


@runtime_checkable
class GoalStore(Protocol):
    async def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        owner_agent_id: str,
        desired_state: str,
        success_conditions: tuple[str, ...],
        stop_conditions: tuple[str, ...],
        author_principal_id: str,
        parent_goal_id: str | None = None,
        goal_id: str | None = None,
    ) -> tuple[Goal, GoalRevision]: ...

    async def get(self, goal_id: str) -> Goal | None: ...

    async def list_for_project(self, workspace_id: str, project_id: str) -> list[Goal]: ...

    async def list_owned_by_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        """The ACTIVE Goals this Agent owns in this Workspace."""
        ...

    async def revise(
        self,
        goal_id: str,
        *,
        expected_revision: int,
        desired_state: str,
        success_conditions: tuple[str, ...],
        stop_conditions: tuple[str, ...],
        author_principal_id: str,
    ) -> GoalRevision: ...

    async def transition(
        self,
        goal_id: str,
        *,
        expected_state: GoalState,
        expected_revision: int,
        to_state: GoalState,
    ) -> Goal: ...

    async def reassign_owner(
        self,
        goal_id: str,
        *,
        expected_revision: int,
        owner_agent_id: str,
        author_principal_id: str,
    ) -> GoalRevision: ...

    async def get_revision(self, goal_id: str, revision: int) -> GoalRevision | None: ...

    async def list_revisions(self, goal_id: str) -> list[GoalRevision]: ...


def new_goal_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


def check_revisable(goal: Goal, expected_revision: int) -> None:
    """Shared by every backend so the refusal order is one decision."""
    if goal.state.is_terminal:
        raise GoalTransitionRefused(f"Goal {goal.goal_id!r} is {goal.state}; terminal is final")
    if goal.current_revision != expected_revision:
        raise GoalRevisionConflict(
            f"Goal {goal.goal_id!r} is at revision {goal.current_revision}, not {expected_revision}"
        )


def check_transition(
    goal: Goal, *, expected_state: GoalState, expected_revision: int, to_state: GoalState
) -> None:
    if goal.state.is_terminal:
        raise GoalTransitionRefused(f"Goal {goal.goal_id!r} is {goal.state}; terminal is final")
    if goal.state is not expected_state or goal.current_revision != expected_revision:
        raise GoalRevisionConflict(
            f"Goal {goal.goal_id!r} is {goal.state} at revision {goal.current_revision}, "
            f"not {expected_state} at {expected_revision}"
        )
    if to_state is goal.state:
        raise GoalTransitionRefused(f"Goal {goal.goal_id!r} is already {to_state}")


def check_reassign(goal: Goal, expected_revision: int, owner_agent_id: str) -> None:
    check_revisable(goal, expected_revision)
    require_text(owner_agent_id=owner_agent_id)
    if owner_agent_id == goal.owner_agent_id:
        raise GoalTransitionRefused(f"Goal {goal.goal_id!r} is already owned by {owner_agent_id!r}")


def require_text(**values: str) -> None:
    for name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")


def conditions(name: str, value: tuple[str, ...]) -> tuple[str, ...]:
    """A tuple of non-empty strings; a bare string is refused, not split into characters."""
    if isinstance(value, str) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{name} must be a sequence of non-empty strings")
    return tuple(value)


def new_revision(
    goal_id: str,
    revision: int,
    *,
    owner_agent_id: str,
    desired_state: str,
    success_conditions: tuple[str, ...],
    stop_conditions: tuple[str, ...],
    author_principal_id: str,
    created_at: datetime,
) -> GoalRevision:
    """Every revision any backend writes is validated here, once."""
    require_text(
        owner_agent_id=owner_agent_id,
        desired_state=desired_state,
        author_principal_id=author_principal_id,
    )
    return GoalRevision(
        goal_id=goal_id,
        revision=revision,
        owner_agent_id=owner_agent_id,
        desired_state=desired_state,
        success_conditions=conditions("success_conditions", success_conditions),
        stop_conditions=conditions("stop_conditions", stop_conditions),
        author_principal_id=author_principal_id,
        created_at=created_at,
    )


def new_goal(
    *,
    goal_id: str | None,
    workspace_id: str,
    project_id: str,
    parent_goal_id: str | None,
    first: GoalRevision,
) -> Goal:
    goal_id = goal_id or first.goal_id
    require_text(goal_id=goal_id, workspace_id=workspace_id, project_id=project_id)
    return Goal(
        goal_id=goal_id,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_agent_id=first.owner_agent_id,
        parent_goal_id=parent_goal_id,
        state=GoalState.ACTIVE,
        current_revision=1,
        created_at=first.created_at,
        updated_at=first.created_at,
    )


def check_parent(parent: Goal | None, *, parent_goal_id: str, project_id: str) -> None:
    """One message for a missing and a foreign parent, so neither is disclosed."""
    if parent is None or parent.project_id != project_id:
        raise GoalLineageError(f"parent Goal {parent_goal_id!r} is not in Project {project_id!r}")
    if parent.state.is_terminal:
        raise GoalTransitionRefused(
            f"parent Goal {parent_goal_id!r} is {parent.state}; a terminal Goal takes no Subgoals"
        )


def project_not_in_workspace(project_id: str, workspace_id: str) -> GoalLineageError:
    return GoalLineageError(f"Project {project_id!r} is not in Workspace {workspace_id!r}")


class InMemoryGoalStore:
    """Reference Goal store; Projects are resolved through the paired Project store."""

    def __init__(self, *, project_store: ProjectScopeStore) -> None:
        self._project_store = project_store
        self._goals: dict[str, Goal] = {}
        self._revisions: dict[str, list[GoalRevision]] = {}

    async def create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        owner_agent_id: str,
        desired_state: str,
        success_conditions: tuple[str, ...],
        stop_conditions: tuple[str, ...],
        author_principal_id: str,
        parent_goal_id: str | None = None,
        goal_id: str | None = None,
    ) -> tuple[Goal, GoalRevision]:
        first = new_revision(
            goal_id or new_goal_id(),
            1,
            owner_agent_id=owner_agent_id,
            desired_state=desired_state,
            success_conditions=success_conditions,
            stop_conditions=stop_conditions,
            author_principal_id=author_principal_id,
            created_at=now(),
        )
        goal = new_goal(
            goal_id=first.goal_id,
            workspace_id=workspace_id,
            project_id=project_id,
            parent_goal_id=parent_goal_id,
            first=first,
        )
        project = await self._project_store.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise project_not_in_workspace(project_id, workspace_id)
        if parent_goal_id is not None:
            check_parent(
                self._goals.get(parent_goal_id),
                parent_goal_id=parent_goal_id,
                project_id=project_id,
            )
        if goal.goal_id in self._goals:
            raise ValueError(f"Goal {goal.goal_id!r} already exists")
        self._goals[goal.goal_id] = goal
        self._revisions[goal.goal_id] = [first]
        return goal, first

    async def get(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    async def list_for_project(self, workspace_id: str, project_id: str) -> list[Goal]:
        return self._sorted(
            goal
            for goal in self._goals.values()
            if goal.workspace_id == workspace_id and goal.project_id == project_id
        )

    async def list_owned_by_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        return self._sorted(
            goal
            for goal in self._goals.values()
            if goal.workspace_id == workspace_id
            and goal.owner_agent_id == agent_id
            and goal.state is GoalState.ACTIVE
        )

    async def revise(
        self,
        goal_id: str,
        *,
        expected_revision: int,
        desired_state: str,
        success_conditions: tuple[str, ...],
        stop_conditions: tuple[str, ...],
        author_principal_id: str,
    ) -> GoalRevision:
        goal = self._require(goal_id)
        check_revisable(goal, expected_revision)
        return self._append(
            goal,
            new_revision(
                goal_id,
                goal.current_revision + 1,
                owner_agent_id=goal.owner_agent_id,
                desired_state=desired_state,
                success_conditions=success_conditions,
                stop_conditions=stop_conditions,
                author_principal_id=author_principal_id,
                created_at=now(),
            ),
        )

    async def reassign_owner(
        self,
        goal_id: str,
        *,
        expected_revision: int,
        owner_agent_id: str,
        author_principal_id: str,
    ) -> GoalRevision:
        goal = self._require(goal_id)
        check_reassign(goal, expected_revision, owner_agent_id)
        latest = self._revisions[goal_id][-1]
        return self._append(
            goal,
            new_revision(
                goal_id,
                goal.current_revision + 1,
                owner_agent_id=owner_agent_id,
                desired_state=latest.desired_state,
                success_conditions=latest.success_conditions,
                stop_conditions=latest.stop_conditions,
                author_principal_id=author_principal_id,
                created_at=now(),
            ),
        )

    async def transition(
        self,
        goal_id: str,
        *,
        expected_state: GoalState,
        expected_revision: int,
        to_state: GoalState,
    ) -> Goal:
        goal = self._require(goal_id)
        check_transition(
            goal,
            expected_state=expected_state,
            expected_revision=expected_revision,
            to_state=to_state,
        )
        moved = replace(goal, state=to_state, updated_at=now())
        self._goals[goal_id] = moved
        return moved

    async def get_revision(self, goal_id: str, revision: int) -> GoalRevision | None:
        for item in self._revisions.get(goal_id, []):
            if item.revision == revision:
                return item
        return None

    async def list_revisions(self, goal_id: str) -> list[GoalRevision]:
        return list(self._revisions.get(goal_id, []))

    @staticmethod
    def _sorted(goals: Iterable[Goal]) -> list[Goal]:
        return sorted(goals, key=lambda goal: (goal.created_at, goal.goal_id))

    def _require(self, goal_id: str) -> Goal:
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalNotFound(goal_id)
        return goal

    def _append(self, goal: Goal, revision: GoalRevision) -> GoalRevision:
        self._revisions[goal.goal_id].append(revision)
        self._goals[goal.goal_id] = replace(
            goal,
            owner_agent_id=revision.owner_agent_id,
            current_revision=revision.revision,
            updated_at=revision.created_at,
        )
        return revision


__all__ = ["GoalStore", "InMemoryGoalStore"]
