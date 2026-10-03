"""SQLite persistence for canonical Goals and their revisions (#1572).

The revision table carries `PRIMARY KEY (goal_id, goal_revision)`. Append-only ordering
is therefore a property of the database rather than of a read-then-write in
this process: two writers racing the same next number both pass any check
one of them could make in Python, and exactly one survives the insert.

Every mutation goes through `_serialized_write`. SQLite opens a transaction
implicitly on a connection's first DML statement, so an unlocked writer left
mid-statement across an `await` makes the next `BEGIN IMMEDIATE` fail outright
rather than merely race -- the reason the Project store takes the same lock.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS canonical_goals (
    goal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    owner_agent_id TEXT NOT NULL,
    parent_goal_id TEXT,
    state TEXT NOT NULL,
    current_revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (parent_goal_id) REFERENCES canonical_goals(goal_id) ON DELETE RESTRICT
);

-- What a persistent Workspace Agent asks on every wake: the non-terminal
-- Goals one Agent owns in one Workspace (#805).
CREATE INDEX IF NOT EXISTS idx_canonical_goals_owner
    ON canonical_goals(workspace_id, owner_agent_id, state);
CREATE INDEX IF NOT EXISTS idx_canonical_goals_parent
    ON canonical_goals(parent_goal_id);
CREATE INDEX IF NOT EXISTS idx_canonical_goals_project
    ON canonical_goals(workspace_id, project_id);

CREATE TABLE IF NOT EXISTS canonical_goal_revisions (
    goal_id TEXT NOT NULL,
    goal_revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (goal_id, goal_revision),
    -- Append-only, enforced by the database rather than by a read-then-write
    -- in one process: two writers racing the same next revision both pass any
    -- Python-side check, and exactly one survives this.
    FOREIGN KEY (goal_id) REFERENCES canonical_goals(goal_id) ON DELETE RESTRICT
);
"""


class SqliteGoalStore:
    """Durable Goal and revision store on an application-owned connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_lock = asyncio.Lock()

    @asynccontextmanager
    async def _serialized_write(self) -> AsyncIterator[None]:
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    async def ensure_schema(self) -> None:
        """Create the canonical Goal tables and their lookup indexes."""

        await self._conn.execute("PRAGMA foreign_keys = ON")
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)

    async def _read_goal(self, workspace_id: str, goal_id: str) -> Goal | None:
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_goals WHERE goal_id = ? AND workspace_id = ?",
            (goal_id, workspace_id),
        )
        row = await cursor.fetchone()
        return None if row is None else Goal.model_validate_json(row[0])

    async def _require(self, workspace_id: str, goal_id: str) -> Goal:
        goal = await self._read_goal(workspace_id, goal_id)
        if goal is None:
            raise GoalNotFound(f"Goal {goal_id!r} is not visible in this Workspace")
        return goal

    async def _write_goal(self, goal: Goal) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_goals
               (goal_id, workspace_id, project_id, owner_agent_id, parent_goal_id,
                state, current_revision, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (goal_id) DO UPDATE SET
                 owner_agent_id = excluded.owner_agent_id,
                 state = excluded.state,
                 current_revision = excluded.current_revision,
                 payload = excluded.payload""",
            (
                goal.goal_id,
                goal.workspace_id,
                goal.project_id,
                goal.owner_agent_id,
                goal.parent_goal_id,
                str(goal.state),
                goal.current_revision,
                goal.model_dump_json(),
            ),
        )

    async def create(self, goal: Goal, revision: GoalRevision) -> Goal:
        if revision.goal_id != goal.goal_id:
            raise GoalLineageError("the first revision must belong to the Goal it opens")
        if revision.goal_revision != goal.current_revision:
            raise GoalRevisionConflict("a new Goal must point at the revision it is created with")
        async with self._serialized_write():
            existing = await self._conn.execute(
                "SELECT 1 FROM canonical_goals WHERE goal_id = ?", (goal.goal_id,)
            )
            if await existing.fetchone() is not None:
                raise GoalRevisionConflict(f"Goal {goal.goal_id!r} already exists")
            if goal.parent_goal_id is not None:
                parent = await self._read_goal(goal.workspace_id, goal.parent_goal_id)
                if parent is None:
                    raise GoalLineageError(f"parent Goal {goal.parent_goal_id!r} does not exist")
                if parent.project_id != goal.project_id:
                    raise GoalLineageError(
                        "a Subgoal keeps its parent's Project: "
                        f"parent is in {parent.project_id!r}, "
                        f"child declares {goal.project_id!r}"
                    )
            await self._write_goal(goal)
            await self._write_revision(revision)
            return goal

    async def _write_revision(self, revision: GoalRevision) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_goal_revisions
               (goal_id, goal_revision, payload) VALUES (?, ?, ?)""",
            (
                revision.goal_id,
                revision.goal_revision,
                revision.model_dump_json(),
            ),
        )

    async def get(self, workspace_id: str, goal_id: str) -> Goal | None:
        return await self._read_goal(workspace_id, goal_id)

    async def revise(
        self, workspace_id: str, goal_id: str, *, expected_revision: int, revision: GoalRevision
    ) -> Goal:
        async with self._serialized_write():
            goal = await self._require(workspace_id, goal_id)
            if goal.is_terminal:
                raise GoalStateConflict(f"Goal {goal_id!r} is {goal.state} and cannot be revised")
            if goal.current_revision != expected_revision:
                raise GoalRevisionConflict(
                    f"Goal {goal_id!r} moved to {goal.current_revision!r} "
                    f"while {expected_revision!r} was held"
                )
            if revision.goal_id != goal_id:
                raise GoalLineageError("a revision must belong to the Goal it revises")
            try:
                await self._write_revision(revision)
            except Exception as exc:  # the PRIMARY KEY (goal_id, goal_revision) guard
                raise GoalRevisionConflict(
                    f"revision {revision.goal_revision} is already taken for {goal_id!r}"
                ) from exc
            updated = goal.model_copy(
                update={
                    "current_revision": revision.goal_revision,
                    "updated_at": revision.created_at,
                }
            )
            await self._write_goal(updated)
            return updated

    async def transition(
        self, workspace_id: str, goal_id: str, *, expected_state: GoalState, state: GoalState
    ) -> Goal:
        async with self._serialized_write():
            goal = await self._require(workspace_id, goal_id)
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
            await self._write_goal(updated)
            return updated

    async def reassign(
        self, workspace_id: str, goal_id: str, *, expected_agent_id: str, owner_agent_id: str
    ) -> Goal:
        async with self._serialized_write():
            goal = await self._require(workspace_id, goal_id)
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
            await self._write_goal(updated)
            return updated

    async def revisions(self, workspace_id: str, goal_id: str) -> list[GoalRevision]:
        await self._require(workspace_id, goal_id)
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_goal_revisions WHERE goal_id = ? ORDER BY goal_revision",
            (goal_id,),
        )
        return [GoalRevision.model_validate_json(row[0]) for row in await cursor.fetchall()]

    async def revision(
        self, workspace_id: str, goal_id: str, goal_revision: int
    ) -> GoalRevision | None:
        cursor = await self._conn.execute(
            """SELECT r.payload FROM canonical_goal_revisions r
               JOIN canonical_goals g ON g.goal_id = r.goal_id
               WHERE r.goal_id = ? AND r.goal_revision = ? AND g.workspace_id = ?""",
            (goal_id, goal_revision, workspace_id),
        )
        row = await cursor.fetchone()
        return None if row is None else GoalRevision.model_validate_json(row[0])

    async def active_for_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        placeholders = ", ".join("?" for _ in TERMINAL_GOAL_STATES)
        cursor = await self._conn.execute(
            f"""SELECT payload FROM canonical_goals
                WHERE workspace_id = ? AND owner_agent_id = ?
                  AND state NOT IN ({placeholders})""",
            (workspace_id, agent_id, *(str(s) for s in sorted(TERMINAL_GOAL_STATES))),
        )
        return _ordered(Goal.model_validate_json(row[0]) for row in await cursor.fetchall())

    async def children(self, workspace_id: str, goal_id: str) -> list[Goal]:
        await self._require(workspace_id, goal_id)
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_goals WHERE workspace_id = ? AND parent_goal_id = ?",
            (workspace_id, goal_id),
        )
        return _ordered(Goal.model_validate_json(row[0]) for row in await cursor.fetchall())


def _ordered(goals: Any) -> list[Goal]:
    """Oldest first, with the id breaking a tie two rows in one millisecond make."""

    return sorted(goals, key=lambda g: (g.created_at, g.goal_id))


__all__ = ["SqliteGoalStore"]
