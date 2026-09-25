"""SQLite persistence for the canonical Goal (homelab/single-instance, #1572).

The same protocol and rules as `InMemoryGoalStore`, read against the same
conformance suite. Goals reference `canonical_projects`, so this store shares
the SQLite Project scope store's connection and writes inside *its*
`transaction()`: one `asyncio.Lock` and one `BEGIN IMMEDIATE` per connection,
for the reason `SqliteWorkspaceStore` records (#1121). Holding the write lock
across the read-check-write is what makes a stale revise lose rather than race.

A Subgoal's parent is held to the same Project by a composite foreign key on
`(parent_goal_id, project_id)`, so the database refuses a cross-Project parent
even from a writer that skipped the store's own check. Timestamps are ISO-8601
text in UTC, which round-trips an aware `datetime` exactly.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.goals.store import (
    check_parent,
    check_reassign,
    check_revisable,
    check_transition,
    new_goal,
    new_goal_id,
    new_revision,
    now,
    project_not_in_workspace,
)
from maistro.goals.types import (
    Goal,
    GoalNotFound,
    GoalRevision,
    GoalState,
)
from maistro.projects.scope_store import TransactionalProjectScopeStore
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

    from maistro.projects.scope_store import ProjectScopeStore


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    parent_goal_id TEXT,
    owner_agent_id TEXT NOT NULL,
    state TEXT NOT NULL
        CHECK (state IN ('active', 'satisfied', 'cancelled', 'failed', 'superseded')),
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (goal_id, project_id),
    FOREIGN KEY (project_id) REFERENCES canonical_projects(project_id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_goal_id, project_id)
        REFERENCES goals(goal_id, project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_goals_project ON goals(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_goal_id, project_id);
CREATE INDEX IF NOT EXISTS idx_goals_active_owner
    ON goals(workspace_id, owner_agent_id)
    WHERE state = 'active';

CREATE TABLE IF NOT EXISTS goal_revisions (
    goal_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    owner_agent_id TEXT NOT NULL,
    desired_state TEXT NOT NULL,
    success_conditions TEXT NOT NULL,
    stop_conditions TEXT NOT NULL,
    author_principal_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (goal_id, revision),
    FOREIGN KEY (goal_id) REFERENCES goals(goal_id) ON DELETE CASCADE
);
"""

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
        created_at=datetime.fromisoformat(row[7]),
        updated_at=datetime.fromisoformat(row[8]),
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
        created_at=datetime.fromisoformat(row[7]),
    )


class SqliteGoalStore:
    """Durable Goal store for a single instance."""

    def __init__(self, conn: aiosqlite.Connection, *, project_store: ProjectScopeStore) -> None:
        if not isinstance(project_store, TransactionalProjectScopeStore):
            msg = (
                "SqliteGoalStore writes inside the Project store's transaction, and "
                f"{type(project_store).__name__} has none. Pair it with "
                "SqliteProjectScopeStore on the same connection."
            )
            raise TypeError(msg)
        self._conn = conn
        self._project_store: TransactionalProjectScopeStore = project_store

    async def ensure_schema(self) -> None:
        await self._conn.execute("PRAGMA foreign_keys = ON")
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)

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
        revision = new_revision(
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
            goal_id=revision.goal_id,
            workspace_id=workspace_id,
            project_id=project_id,
            parent_goal_id=parent_goal_id,
            first=revision,
        )
        async with self._project_store.transaction() as conn:
            await self._check_lineage(conn, goal)
            if await self._read_goal(conn, goal.goal_id) is not None:
                raise ValueError(f"Goal {goal.goal_id!r} already exists")
            await conn.execute(
                f"INSERT INTO goals ({_GOAL_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",  # nosec B608
                (
                    goal.goal_id,
                    goal.workspace_id,
                    goal.project_id,
                    goal.owner_agent_id,
                    goal.parent_goal_id,
                    goal.state.value,
                    goal.current_revision,
                    goal.created_at.isoformat(),
                    goal.updated_at.isoformat(),
                ),
            )
            await self._insert_revision(conn, revision)
        return goal, revision

    async def get(self, goal_id: str) -> Goal | None:
        return await self._read_goal(self._conn, goal_id)

    async def list_for_project(self, workspace_id: str, project_id: str) -> list[Goal]:
        async with self._conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM goals "  # nosec B608
            "WHERE workspace_id = ? AND project_id = ? ORDER BY created_at, goal_id",
            (workspace_id, project_id),
        ) as cursor:
            return [_goal(row) for row in await cursor.fetchall()]

    async def list_owned_by_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        async with self._conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM goals "  # nosec B608
            "WHERE workspace_id = ? AND owner_agent_id = ? AND state = 'active' "
            "ORDER BY created_at, goal_id",
            (workspace_id, agent_id),
        ) as cursor:
            return [_goal(row) for row in await cursor.fetchall()]

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
        async with self._project_store.transaction() as conn:
            goal = await self._require(conn, goal_id)
            check_revisable(goal, expected_revision)
            return await self._append(
                conn,
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
        async with self._project_store.transaction() as conn:
            goal = await self._require(conn, goal_id)
            check_reassign(goal, expected_revision, owner_agent_id)
            latest = await self._read_revision(conn, goal_id, goal.current_revision)
            assert latest is not None  # nosec B101 - the pointer's row is written with it
            return await self._append(
                conn,
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
        async with self._project_store.transaction() as conn:
            goal = await self._require(conn, goal_id)
            check_transition(
                goal,
                expected_state=expected_state,
                expected_revision=expected_revision,
                to_state=to_state,
            )
            stamp = now()
            await conn.execute(
                "UPDATE goals SET state = ?, updated_at = ? WHERE goal_id = ?",
                (to_state.value, stamp.isoformat(), goal_id),
            )
        return replace(goal, state=to_state, updated_at=stamp)

    async def get_revision(self, goal_id: str, revision: int) -> GoalRevision | None:
        return await self._read_revision(self._conn, goal_id, revision)

    async def list_revisions(self, goal_id: str) -> list[GoalRevision]:
        async with self._conn.execute(
            f"SELECT {_REVISION_COLUMNS} FROM goal_revisions "  # nosec B608
            "WHERE goal_id = ? ORDER BY revision",
            (goal_id,),
        ) as cursor:
            return [_revision(row) for row in await cursor.fetchall()]

    async def _check_lineage(self, conn: Any, goal: Goal) -> None:
        async with conn.execute(
            "SELECT workspace_id FROM canonical_projects WHERE project_id = ?",
            (goal.project_id,),
        ) as cursor:
            project = await cursor.fetchone()
        if project is None or project[0] != goal.workspace_id:
            raise project_not_in_workspace(goal.project_id, goal.workspace_id)
        if goal.parent_goal_id is not None:
            check_parent(
                await self._read_goal(conn, goal.parent_goal_id),
                parent_goal_id=goal.parent_goal_id,
                project_id=goal.project_id,
            )

    async def _append(self, conn: Any, goal: Goal, revision: GoalRevision) -> GoalRevision:
        await self._insert_revision(conn, revision)
        await conn.execute(
            "UPDATE goals SET current_revision = ?, owner_agent_id = ?, updated_at = ? "
            "WHERE goal_id = ?",
            (
                revision.revision,
                revision.owner_agent_id,
                revision.created_at.isoformat(),
                goal.goal_id,
            ),
        )
        return revision

    @staticmethod
    async def _insert_revision(conn: Any, revision: GoalRevision) -> None:
        await conn.execute(
            f"INSERT INTO goal_revisions ({_REVISION_COLUMNS}) "  # nosec B608
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                revision.goal_id,
                revision.revision,
                revision.owner_agent_id,
                revision.desired_state,
                json.dumps(list(revision.success_conditions)),
                json.dumps(list(revision.stop_conditions)),
                revision.author_principal_id,
                revision.created_at.isoformat(),
            ),
        )

    async def _require(self, conn: Any, goal_id: str) -> Goal:
        goal = await self._read_goal(conn, goal_id)
        if goal is None:
            raise GoalNotFound(goal_id)
        return goal

    @staticmethod
    async def _read_goal(conn: Any, goal_id: str) -> Goal | None:
        async with conn.execute(
            f"SELECT {_GOAL_COLUMNS} FROM goals WHERE goal_id = ?",  # nosec B608
            (goal_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _goal(row) if row is not None else None

    @staticmethod
    async def _read_revision(conn: Any, goal_id: str, revision: int) -> GoalRevision | None:
        async with conn.execute(
            f"SELECT {_REVISION_COLUMNS} FROM goal_revisions "  # nosec B608
            "WHERE goal_id = ? AND revision = ?",
            (goal_id, revision),
        ) as cursor:
            row = await cursor.fetchone()
        return _revision(row) if row is not None else None


__all__ = ["SqliteGoalStore"]
