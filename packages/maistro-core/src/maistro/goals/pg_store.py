"""PostgreSQL persistence for the canonical Goal (#1572).

The durable, replica-shareable twin of `InMemoryGoalStore`, read against the
same conformance suite. Tables come from `alembic/versions/041_goals.py`; this
store creates no schema of its own, so there is one schema owner.

Every write that checks the Goal before changing it takes `SELECT ... FOR
UPDATE` on the Goal row first. Two writers holding the same expected revision
therefore serialise on that row: the second reads the revision the first
wrote and is refused, which is the "exactly one winner" the contract
promises. The `(goal_id, revision)` primary key on `goal_revisions` is the
backstop if a writer ever skipped the lock.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from maistro.goals.store import (
    PARENT_NOT_IN_PROJECT,
    PROJECT_NOT_IN_WORKSPACE,
    check_revisable,
    check_transition,
    new_goal_id,
    now,
)
from maistro.goals.types import (
    Goal,
    GoalLineageError,
    GoalNotFound,
    GoalRevision,
    GoalState,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

_GOAL_COLUMNS = (
    "goal_id, workspace_id, project_id, owner_agent_id, parent_goal_id, state, "
    "current_revision, created_at, updated_at"
)
_REVISION_COLUMNS = (
    "goal_id, revision, owner_agent_id, desired_state, success_conditions, "
    "stop_conditions, author_principal_id, created_at"
)


def _goal(row: Sequence[Any]) -> Goal:
    return Goal(
        goal_id=row[0],
        workspace_id=row[1],
        project_id=row[2],
        owner_agent_id=row[3],
        parent_goal_id=row[4],
        state=GoalState(row[5]),
        current_revision=int(row[6]),
        created_at=row[7],
        updated_at=row[8],
    )


def _revision(row: Sequence[Any]) -> GoalRevision:
    return GoalRevision(
        goal_id=row[0],
        revision=int(row[1]),
        owner_agent_id=row[2],
        desired_state=row[3],
        success_conditions=tuple(json.loads(row[4])),
        stop_conditions=tuple(json.loads(row[5])),
        author_principal_id=row[6],
        created_at=row[7],
    )


class PgGoalStore:
    """Durable Goal store shared by every replica on one database."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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
        stamp = now()
        goal = Goal(
            goal_id=goal_id or new_goal_id(),
            workspace_id=workspace_id,
            project_id=project_id,
            owner_agent_id=owner_agent_id,
            parent_goal_id=parent_goal_id,
            state=GoalState.ACTIVE,
            current_revision=1,
            created_at=stamp,
            updated_at=stamp,
        )
        revision = GoalRevision(
            goal_id=goal.goal_id,
            revision=1,
            owner_agent_id=owner_agent_id,
            desired_state=desired_state,
            success_conditions=tuple(success_conditions),
            stop_conditions=tuple(stop_conditions),
            author_principal_id=author_principal_id,
            created_at=stamp,
        )
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn, conn.transaction():
            await self._check_lineage(conn, goal)
            inserted = await conn.fetchval(
                f"INSERT INTO goals ({_GOAL_COLUMNS}) "  # nosec B608
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                "ON CONFLICT (goal_id) DO NOTHING RETURNING goal_id",
                goal.goal_id,
                goal.workspace_id,
                goal.project_id,
                goal.owner_agent_id,
                goal.parent_goal_id,
                goal.state.value,
                goal.current_revision,
                goal.created_at,
                goal.updated_at,
            )
            if inserted is None:
                raise ValueError(f"Goal {goal.goal_id!r} already exists")
            await self._insert_revision(conn, revision)
        return goal, revision

    async def get(self, goal_id: str) -> Goal | None:
        async with self._pool.acquire() as conn:
            return await self._read_goal(conn, goal_id)

    async def list_for_project(self, workspace_id: str, project_id: str) -> list[Goal]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_GOAL_COLUMNS} FROM goals "  # nosec B608
                "WHERE workspace_id = $1 AND project_id = $2 ORDER BY created_at, goal_id",
                workspace_id,
                project_id,
            )
        return [_goal(row) for row in rows]

    async def list_owned_by_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_GOAL_COLUMNS} FROM goals "  # nosec B608
                "WHERE workspace_id = $1 AND owner_agent_id = $2 AND state = 'active' "
                "ORDER BY created_at, goal_id",
                workspace_id,
                agent_id,
            )
        return [_goal(row) for row in rows]

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
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn, conn.transaction():
            goal = await self._lock(conn, goal_id)
            check_revisable(goal, expected_revision)
            return await self._append(
                conn,
                GoalRevision(
                    goal_id=goal_id,
                    revision=goal.current_revision + 1,
                    owner_agent_id=goal.owner_agent_id,
                    desired_state=desired_state,
                    success_conditions=tuple(success_conditions),
                    stop_conditions=tuple(stop_conditions),
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
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn, conn.transaction():
            goal = await self._lock(conn, goal_id)
            check_revisable(goal, expected_revision)
            latest = await self._read_revision(conn, goal_id, goal.current_revision)
            assert latest is not None  # nosec B101 - the pointer's row is written with it
            return await self._append(
                conn,
                replace(
                    latest,
                    revision=goal.current_revision + 1,
                    owner_agent_id=owner_agent_id,
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
        conn: asyncpg.Connection
        async with self._pool.acquire() as conn, conn.transaction():
            goal = await self._lock(conn, goal_id)
            check_transition(
                goal,
                expected_state=expected_state,
                expected_revision=expected_revision,
                to_state=to_state,
            )
            moved = replace(goal, state=to_state, updated_at=now())
            await conn.execute(
                "UPDATE goals SET state = $2, updated_at = $3 WHERE goal_id = $1",
                goal_id,
                moved.state.value,
                moved.updated_at,
            )
        return moved

    async def get_revision(self, goal_id: str, revision: int) -> GoalRevision | None:
        async with self._pool.acquire() as conn:
            return await self._read_revision(conn, goal_id, revision)

    async def list_revisions(self, goal_id: str) -> list[GoalRevision]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_REVISION_COLUMNS} FROM goal_revisions "  # nosec B608
                "WHERE goal_id = $1 ORDER BY revision",
                goal_id,
            )
        return [_revision(row) for row in rows]

    @staticmethod
    async def _check_lineage(conn: Any, goal: Goal) -> None:
        project_workspace = await conn.fetchval(
            "SELECT workspace_id FROM canonical_projects WHERE project_id = $1 FOR SHARE",
            goal.project_id,
        )
        if project_workspace != goal.workspace_id:
            raise GoalLineageError(
                PROJECT_NOT_IN_WORKSPACE.format(
                    project_id=goal.project_id, workspace_id=goal.workspace_id
                )
            )
        if goal.parent_goal_id is None:
            return
        parent_project = await conn.fetchval(
            "SELECT project_id FROM goals WHERE goal_id = $1 FOR SHARE",
            goal.parent_goal_id,
        )
        if parent_project != goal.project_id:
            raise GoalLineageError(
                PARENT_NOT_IN_PROJECT.format(
                    parent_goal_id=goal.parent_goal_id, project_id=goal.project_id
                )
            )

    async def _append(self, conn: Any, revision: GoalRevision) -> GoalRevision:
        await self._insert_revision(conn, revision)
        await conn.execute(
            "UPDATE goals SET current_revision = $2, owner_agent_id = $3, updated_at = $4 "
            "WHERE goal_id = $1",
            revision.goal_id,
            revision.revision,
            revision.owner_agent_id,
            revision.created_at,
        )
        return revision

    @staticmethod
    async def _insert_revision(conn: Any, revision: GoalRevision) -> None:
        await conn.execute(
            f"INSERT INTO goal_revisions ({_REVISION_COLUMNS}) "  # nosec B608
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            revision.goal_id,
            revision.revision,
            revision.owner_agent_id,
            revision.desired_state,
            json.dumps(list(revision.success_conditions)),
            json.dumps(list(revision.stop_conditions)),
            revision.author_principal_id,
            revision.created_at,
        )

    @staticmethod
    async def _lock(conn: Any, goal_id: str) -> Goal:
        row = await conn.fetchrow(
            f"SELECT {_GOAL_COLUMNS} FROM goals WHERE goal_id = $1 FOR UPDATE",  # nosec B608
            goal_id,
        )
        if row is None:
            raise GoalNotFound(goal_id)
        return _goal(row)

    @staticmethod
    async def _read_goal(conn: Any, goal_id: str) -> Goal | None:
        row = await conn.fetchrow(
            f"SELECT {_GOAL_COLUMNS} FROM goals WHERE goal_id = $1",  # nosec B608
            goal_id,
        )
        return _goal(row) if row is not None else None

    @staticmethod
    async def _read_revision(conn: Any, goal_id: str, revision: int) -> GoalRevision | None:
        row = await conn.fetchrow(
            f"SELECT {_REVISION_COLUMNS} FROM goal_revisions "  # nosec B608
            "WHERE goal_id = $1 AND revision = $2",
            goal_id,
            revision,
        )
        return _revision(row) if row is not None else None


__all__ = ["PgGoalStore"]
