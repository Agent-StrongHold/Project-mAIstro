"""PostgreSQL persistence for canonical Goals and their revisions (#1572).

The durable twin of `sqlite_store.py`. Same protocol, same errors, same
semantics -- the conformance suite runs one set of bodies against all three
stores, because "implements the same protocol as" being a docstring rather
than a test is how two backends come to disagree.

What differs is the concurrency, not the SQL. SQLite serialises writers at the
database, so its read-then-write critical section is enough on its own. A pool
does not serialise anything, so here the `PRIMARY KEY (goal_id, goal_revision)`
constraint is the primary defence rather than a backstop: two reconcilers can
both read the same current revision, both compute the same next number, and
only one can insert it. The compare-and-set below narrows the window; the
constraint closes it.

Payloads are JSONB and come back as dicts because the pool registers a JSON
codec, which is why this reads `model_of` where the SQLite store reads
`model_validate_json`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
from maistro.runs.evidence_json import json_of, model_of

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS canonical_goals (
        goal_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        owner_agent_id TEXT NOT NULL,
        parent_goal_id TEXT REFERENCES canonical_goals(goal_id) ON DELETE RESTRICT,
        state TEXT NOT NULL,
        current_revision INTEGER NOT NULL,
        payload JSONB NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_canonical_goals_owner
        ON canonical_goals(workspace_id, owner_agent_id, state)""",
    """CREATE INDEX IF NOT EXISTS idx_canonical_goals_parent
        ON canonical_goals(parent_goal_id)""",
    """CREATE INDEX IF NOT EXISTS idx_canonical_goals_project
        ON canonical_goals(workspace_id, project_id)""",
    """CREATE TABLE IF NOT EXISTS canonical_goal_revisions (
        goal_id TEXT NOT NULL REFERENCES canonical_goals(goal_id) ON DELETE RESTRICT,
        goal_revision INTEGER NOT NULL,
        payload JSONB NOT NULL,
        PRIMARY KEY (goal_id, goal_revision)
    )""",
)


class PgGoalStore:
    """Durable Goal and revision store on a shared PostgreSQL pool."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            for statement in _SCHEMA:
                await conn.execute(statement)

    async def _read_goal(self, conn: Any, workspace_id: str, goal_id: str) -> Goal | None:
        row = await conn.fetchrow(
            "SELECT payload FROM canonical_goals WHERE goal_id = $1 AND workspace_id = $2",
            goal_id,
            workspace_id,
        )
        return None if row is None else model_of(Goal, row["payload"])

    async def _require(self, conn: Any, workspace_id: str, goal_id: str) -> Goal:
        goal = await self._read_goal(conn, workspace_id, goal_id)
        if goal is None:
            raise GoalNotFound(f"Goal {goal_id!r} is not visible in this Workspace")
        return goal

    async def _write_goal(self, conn: Any, goal: Goal) -> None:
        await conn.execute(
            """INSERT INTO canonical_goals
               (goal_id, workspace_id, project_id, owner_agent_id, parent_goal_id,
                state, current_revision, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::text::jsonb)
               ON CONFLICT (goal_id) DO UPDATE SET
                 owner_agent_id = EXCLUDED.owner_agent_id,
                 state = EXCLUDED.state,
                 current_revision = EXCLUDED.current_revision,
                 payload = EXCLUDED.payload""",
            goal.goal_id,
            goal.workspace_id,
            goal.project_id,
            goal.owner_agent_id,
            goal.parent_goal_id,
            str(goal.state),
            goal.current_revision,
            json_of(goal),
        )

    async def _write_revision(self, conn: Any, revision: GoalRevision) -> None:
        await conn.execute(
            """INSERT INTO canonical_goal_revisions
               (goal_id, goal_revision, payload)
               VALUES ($1, $2, $3::text::jsonb)""",
            revision.goal_id,
            revision.goal_revision,
            json_of(revision),
        )

    async def create(self, goal: Goal, revision: GoalRevision) -> Goal:
        if revision.goal_id != goal.goal_id:
            raise GoalLineageError("the first revision must belong to the Goal it opens")
        if revision.goal_revision != goal.current_revision:
            raise GoalRevisionConflict("a new Goal must point at the revision it is created with")
        async with self._pool.acquire() as conn, conn.transaction():
            if await conn.fetchrow(
                "SELECT 1 FROM canonical_goals WHERE goal_id = $1", goal.goal_id
            ):
                raise GoalRevisionConflict(f"Goal {goal.goal_id!r} already exists")
            if goal.parent_goal_id is not None:
                parent = await self._read_goal(conn, goal.workspace_id, goal.parent_goal_id)
                if parent is None:
                    raise GoalLineageError(f"parent Goal {goal.parent_goal_id!r} does not exist")
                if parent.project_id != goal.project_id:
                    raise GoalLineageError(
                        "a Subgoal keeps its parent's Project: "
                        f"parent is in {parent.project_id!r}, "
                        f"child declares {goal.project_id!r}"
                    )
            await self._write_goal(conn, goal)
            await self._write_revision(conn, revision)
            return goal

    async def get(self, workspace_id: str, goal_id: str) -> Goal | None:
        async with self._pool.acquire() as conn:
            return await self._read_goal(conn, workspace_id, goal_id)

    async def revise(
        self, workspace_id: str, goal_id: str, *, expected_revision: int, revision: GoalRevision
    ) -> Goal:
        async with self._pool.acquire() as conn, conn.transaction():
            goal = await self._require(conn, workspace_id, goal_id)
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
                await self._write_revision(conn, revision)
            except Exception as exc:  # PRIMARY KEY (goal_id, goal_revision)
                raise GoalRevisionConflict(
                    f"revision {revision.goal_revision} is already taken for {goal_id!r}"
                ) from exc
            updated = goal.model_copy(
                update={
                    "current_revision": revision.goal_revision,
                    "updated_at": revision.created_at,
                }
            )
            await self._write_goal(conn, updated)
            return updated

    async def transition(
        self, workspace_id: str, goal_id: str, *, expected_state: GoalState, state: GoalState
    ) -> Goal:
        async with self._pool.acquire() as conn, conn.transaction():
            goal = await self._require(conn, workspace_id, goal_id)
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
            await self._write_goal(conn, updated)
            return updated

    async def reassign(
        self, workspace_id: str, goal_id: str, *, expected_agent_id: str, owner_agent_id: str
    ) -> Goal:
        async with self._pool.acquire() as conn, conn.transaction():
            goal = await self._require(conn, workspace_id, goal_id)
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
            await self._write_goal(conn, updated)
            return updated

    async def revisions(self, workspace_id: str, goal_id: str) -> list[GoalRevision]:
        async with self._pool.acquire() as conn:
            await self._require(conn, workspace_id, goal_id)
            rows = await conn.fetch(
                "SELECT payload FROM canonical_goal_revisions WHERE goal_id = $1 ORDER BY goal_revision",
                goal_id,
            )
            return [model_of(GoalRevision, row["payload"]) for row in rows]

    async def revision(
        self, workspace_id: str, goal_id: str, goal_revision: int
    ) -> GoalRevision | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT r.payload FROM canonical_goal_revisions r
                   JOIN canonical_goals g ON g.goal_id = r.goal_id
                   WHERE r.goal_id = $1 AND r.goal_revision = $2 AND g.workspace_id = $3""",
                goal_id,
                goal_revision,
                workspace_id,
            )
            return None if row is None else model_of(GoalRevision, row["payload"])

    async def active_for_agent(self, workspace_id: str, agent_id: str) -> list[Goal]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM canonical_goals
                   WHERE workspace_id = $1 AND owner_agent_id = $2
                     AND state <> ALL($3::text[])""",
                workspace_id,
                agent_id,
                [str(s) for s in sorted(TERMINAL_GOAL_STATES)],
            )
            return _ordered(model_of(Goal, row["payload"]) for row in rows)

    async def children(self, workspace_id: str, goal_id: str) -> list[Goal]:
        async with self._pool.acquire() as conn:
            await self._require(conn, workspace_id, goal_id)
            rows = await conn.fetch(
                "SELECT payload FROM canonical_goals "
                "WHERE workspace_id = $1 AND parent_goal_id = $2",
                workspace_id,
                goal_id,
            )
            return _ordered(model_of(Goal, row["payload"]) for row in rows)


def _ordered(goals: Any) -> list[Goal]:
    """Oldest first, with the id breaking a tie two rows in one millisecond make.

    Sorted in Python rather than SQL because the ordering keys live inside the
    JSONB payload, exactly as the Project store does it.
    """

    return sorted(goals, key=lambda g: (g.created_at, g.goal_id))


__all__ = ["PgGoalStore"]
