"""The Goal store: one protocol, one conformance suite, three backends.

The in-memory store is the reference — the definition of the contract. The
SQLite and PostgreSQL stores are its durable twins over the deployment's
existing database, and all three run the same conformance suite
(``tests/goals/test_goal_store_conformance.py``), so "the durable stores
behave like the reference" is a comparison, not an assertion in a docstring.

The store persists *desired state and accountability*. It is not a scheduler,
a queue, or a work-status holder: the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` spine keeps its own primitives,
and no method here accepts a Run id, because a Run's outcome never moves Goal
state implicitly (#1572). Mutations are compare-and-set on
``Goal.current_revision``; every backend implements the guard so that a stale
write is refused and two concurrent writers leave exactly one winner.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

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
    transition_is_legal,
)


def require_active(goal: Goal) -> None:
    """Refuse every mutation of a Goal that has left ``active``.

    Terminal states are final; this is the one check every mutation shares,
    kept next to the protocol so the backends cannot grow divergent opinions
    about what "final" means.
    """
    if goal.status in TERMINAL_GOAL_STATUSES:
        raise GoalTransitionError(
            f"{goal.goal_id} is {goal.status.value} and cannot be mutated: "
            "terminal Goal states are final"
        )


@runtime_checkable
class GoalStore(Protocol):
    """Durable home of canonical Goals (`maistro.goals`, ontology owner)."""

    async def create_goal(
        self,
        *,
        workspace_id: str,
        project_id: str,
        agent_id: str,
        draft: GoalRevisionDraft,
        parent_goal_id: str | None = None,
        goal_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Goal:
        """Create a Goal at revision 1 in the ``active`` state.

        ``parent_goal_id`` names the Subgoal parent; the parent must exist in
        the same Workspace and Project, so lineage never crosses a scope
        boundary (:class:`GoalParentInvalid` otherwise).
        """
        ...

    async def get_goal(self, goal_id: str) -> Goal | None:
        """The Goal with this id, or ``None``. Authorization is not this
        method's job — reads go through `maistro.goals.authorization`."""
        ...

    async def append_revision(
        self,
        goal_id: str,
        draft: GoalRevisionDraft,
        *,
        expected_revision: int,
        created_at: datetime | None = None,
    ) -> Goal:
        """Append ``draft`` as the next revision and move the pointer onto it.

        Compare-and-set: refused with :class:`GoalRevisionConflict` unless the
        Goal still sits at ``expected_revision``. The previous revision is
        never rewritten, so the desired state an earlier consumer acted on
        stays readable through :meth:`list_goal_revisions`.
        """
        ...

    async def transition_goal(
        self,
        goal_id: str,
        to_status: GoalStatus,
        *,
        expected_revision: int,
        actor: str,
        at: datetime | None = None,
    ) -> Goal:
        """Move the Goal's lifecycle state, compare-and-set on the revision.

        Only legal moves from ``active`` are accepted (terminal states are
        final); the transition is recorded as an attributed
        :class:`GoalTransitionRecord`. A Run outcome has no path to this
        method — Goal state moves only when a principal decides it does.
        """
        ...

    async def reassign_agent(
        self,
        goal_id: str,
        agent_id: str,
        *,
        expected_revision: int,
        actor: str,
        at: datetime | None = None,
    ) -> Goal:
        """Change the accountable Agent. An explicit, recorded transition:
        the record carries both the old and the new owner."""
        ...

    async def list_goal_revisions(self, goal_id: str) -> list[GoalRevision]:
        """The whole revision chain, oldest first. Append-only: entries are
        never removed or rewritten, so len(chain) only ever grows."""
        ...

    async def list_goal_transitions(self, goal_id: str) -> list[GoalTransitionRecord]:
        """The recorded mutation history, oldest first."""
        ...


class InMemoryGoalStore:
    """The reference implementation. Plain dicts under one lock; durability is
    the durable twins' job, behavior is this class's job."""

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}
        self._revisions: dict[str, list[GoalRevision]] = {}
        self._transitions: dict[str, list[GoalTransitionRecord]] = {}
        self._lock = asyncio.Lock()

    async def create_goal(
        self,
        *,
        workspace_id: str,
        project_id: str,
        agent_id: str,
        draft: GoalRevisionDraft,
        parent_goal_id: str | None = None,
        goal_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Goal:
        async with self._lock:
            if parent_goal_id is not None:
                parent = self._goals.get(parent_goal_id)
                if (
                    parent is None
                    or parent.workspace_id != workspace_id
                    or (parent.project_id != project_id)
                ):
                    raise GoalParentInvalid(parent_goal_id or "")
            fields: dict[str, object] = {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "agent_id": agent_id,
                "parent_goal_id": parent_goal_id,
            }
            if goal_id is not None:
                fields["goal_id"] = goal_id
            if created_at is not None:
                fields["created_at"] = created_at
                fields["updated_at"] = created_at
            goal = Goal.model_validate(fields)
            self._goals[goal.goal_id] = goal
            revision = GoalRevision(
                **{**draft.model_dump(), "revision": 1, "created_at": created_at or _utcnow()}
            )
            self._revisions[goal.goal_id] = [revision]
            self._transitions[goal.goal_id] = []
            return goal.model_copy(deep=True)

    async def get_goal(self, goal_id: str) -> Goal | None:
        async with self._lock:
            goal = self._goals.get(goal_id)
            return goal.model_copy(deep=True) if goal is not None else None

    async def append_revision(
        self,
        goal_id: str,
        draft: GoalRevisionDraft,
        *,
        expected_revision: int,
        created_at: datetime | None = None,
    ) -> Goal:
        async with self._lock:
            goal = self._require(goal_id)
            require_active(goal)
            if goal.current_revision != expected_revision:
                raise GoalRevisionConflict(goal_id, expected_revision, goal.current_revision)
            revision = GoalRevision(
                **{
                    **draft.model_dump(),
                    "revision": expected_revision + 1,
                    "created_at": created_at or _utcnow(),
                }
            )
            updated = goal.model_copy(
                update={"current_revision": revision.revision, "updated_at": _utcnow()}
            )
            self._goals[goal_id] = updated
            self._revisions[goal_id].append(revision)
            return updated.model_copy(deep=True)

    async def transition_goal(
        self,
        goal_id: str,
        to_status: GoalStatus,
        *,
        expected_revision: int,
        actor: str,
        at: datetime | None = None,
    ) -> Goal:
        async with self._lock:
            goal = self._require(goal_id)
            if not transition_is_legal(goal.status, to_status):
                raise GoalTransitionError(
                    f"{goal_id}: a Goal cannot move from {goal.status.value} to {to_status.value}"
                )
            if goal.current_revision != expected_revision:
                raise GoalRevisionConflict(goal_id, expected_revision, goal.current_revision)
            moved_at = at or _utcnow()
            updated = goal.model_copy(update={"status": to_status, "updated_at": moved_at})
            self._goals[goal_id] = updated
            self._transitions[goal_id].append(
                GoalTransitionRecord(
                    goal_id=goal_id,
                    kind=GoalTransitionKind.STATUS,
                    at=moved_at,
                    actor=actor,
                    revision=goal.current_revision,
                    from_status=goal.status,
                    to_status=to_status,
                )
            )
            return updated.model_copy(deep=True)

    async def reassign_agent(
        self,
        goal_id: str,
        agent_id: str,
        *,
        expected_revision: int,
        actor: str,
        at: datetime | None = None,
    ) -> Goal:
        async with self._lock:
            goal = self._require(goal_id)
            require_active(goal)
            if goal.agent_id == agent_id:
                raise GoalTransitionError(
                    f"{goal_id}: {agent_id} already owns this Goal; a reassignment "
                    "must change the owner"
                )
            if goal.current_revision != expected_revision:
                raise GoalRevisionConflict(goal_id, expected_revision, goal.current_revision)
            moved_at = at or _utcnow()
            updated = goal.model_copy(update={"agent_id": agent_id, "updated_at": moved_at})
            self._goals[goal_id] = updated
            self._transitions[goal_id].append(
                GoalTransitionRecord(
                    goal_id=goal_id,
                    kind=GoalTransitionKind.AGENT_REASSIGN,
                    at=moved_at,
                    actor=actor,
                    revision=goal.current_revision,
                    from_agent_id=goal.agent_id,
                    to_agent_id=agent_id,
                )
            )
            return updated.model_copy(deep=True)

    async def list_goal_revisions(self, goal_id: str) -> list[GoalRevision]:
        async with self._lock:
            self._require(goal_id)
            return [revision.model_copy(deep=True) for revision in self._revisions[goal_id]]

    async def list_goal_transitions(self, goal_id: str) -> list[GoalTransitionRecord]:
        async with self._lock:
            self._require(goal_id)
            return [record.model_copy(deep=True) for record in self._transitions[goal_id]]

    def _require(self, goal_id: str) -> Goal:
        goal = self._goals.get(goal_id)
        if goal is None:
            raise GoalNotFound(goal_id)
        return goal


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "GoalStore",
    "InMemoryGoalStore",
    "require_active",
]
