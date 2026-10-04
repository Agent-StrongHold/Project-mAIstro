"""Durable Goal records over the deployment's SQLite database.

Same convention as `workspaces/campaigns/sqlite_store.py`: an injected
``aiosqlite`` connection, plain typed columns for everything that filters or
orders, a JSON payload column the model round-trips through, and an
``ensure_schema()`` under the shared ``serialized_schema_upgrade`` discipline.
The PostgreSQL tables come from Alembic migration ``053``; this store owns the
SQLite DDL, and ``tests/goals/test_goal_schema_parity.py`` holds the two
descriptions of the same tables to one dialect-neutral spec so they cannot
drift apart the way the scope tables once did (#1135).

Three tables, mirroring the model's three append-only surfaces:

* ``canonical_goals`` — identity, scope, ownership and the lifecycle state,
  with ``current_revision`` as the compare-and-set pointer column: the guard
  every mutation is an ``UPDATE ... WHERE current_revision = ?`` against.
* ``canonical_goal_revisions`` — the append-only desired-state chain, one row
  per accepted revision, keyed ``(goal_id, revision)``.
* ``canonical_goal_transitions`` — the recorded, attributed mutation history.

No work state lives here: the canonical spine owns execution, and nothing in
this module accepts a Run id (#1572).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.goals.model import (
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
from maistro.goals.store import require_active
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS canonical_goals (
    goal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    parent_goal_id TEXT,
    status TEXT NOT NULL,
    current_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (parent_goal_id) REFERENCES canonical_goals(goal_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_canonical_goals_project
    ON canonical_goals(project_id);

CREATE TABLE IF NOT EXISTS canonical_goal_revisions (
    goal_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (goal_id, revision),
    FOREIGN KEY (goal_id) REFERENCES canonical_goals(goal_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS canonical_goal_transitions (
    goal_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (goal_id, seq),
    FOREIGN KEY (goal_id) REFERENCES canonical_goals(goal_id) ON DELETE CASCADE
);
"""


def _iso(moment: datetime) -> str:
    return moment.isoformat()


class SqliteGoalStore:
    """The durable twin over one ``aiosqlite`` connection.

    One connection, one operation lock: read-guard-write stays one operation
    for ordinary callers, the same discipline the campaign store runs under.
    The compare-and-set is additionally expressed as a guarded ``UPDATE`` so
    the refusal condition is the row, not only the lock's turn order.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the three tables if the database does not have them yet."""
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SCHEMA)
            await self._conn.commit()

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
                parent = await self._get_goal_row(parent_goal_id)
                if (
                    parent is None
                    or parent.workspace_id != workspace_id
                    or (parent.project_id != project_id)
                ):
                    raise GoalParentInvalid(parent_goal_id or "")
            goal = Goal.model_validate(
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "agent_id": agent_id,
                    "parent_goal_id": parent_goal_id,
                    **({"goal_id": goal_id} if goal_id is not None else {}),
                    **(
                        {"created_at": created_at, "updated_at": created_at}
                        if created_at is not None
                        else {}
                    ),
                }
            )
            revision = GoalRevision(
                **{**draft.model_dump(), "revision": 1, "created_at": created_at or _utcnow()}
            )
            await self._insert_goal(goal, revision)
            await self._conn.commit()
            return goal

    async def get_goal(self, goal_id: str) -> Goal | None:
        async with self._lock:
            return await self._get_goal_row(goal_id)

    async def append_revision(
        self,
        goal_id: str,
        draft: GoalRevisionDraft,
        *,
        expected_revision: int,
        created_at: datetime | None = None,
    ) -> Goal:
        async with self._lock:
            goal = await self._require(goal_id)
            require_active(goal)
            self._check_revision(goal, expected_revision)
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
            cursor = await self._conn.execute(
                """UPDATE canonical_goals
                   SET current_revision = ?, updated_at = ?, payload = ?
                   WHERE goal_id = ? AND current_revision = ? AND status = 'active'""",
                (
                    updated.current_revision,
                    _iso(updated.updated_at),
                    updated.model_dump_json(),
                    goal_id,
                    expected_revision,
                ),
            )
            self._require_won(goal, expected_revision, cursor.rowcount)
            await self._insert_revision(goal_id, revision)
            await self._conn.commit()
            return updated

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
            goal = await self._require(goal_id)
            if not transition_is_legal(goal.status, to_status):
                raise GoalTransitionError(
                    f"{goal_id}: a Goal cannot move from {goal.status.value} to {to_status.value}"
                )
            self._check_revision(goal, expected_revision)
            moved_at = at or _utcnow()
            updated = goal.model_copy(update={"status": to_status, "updated_at": moved_at})
            cursor = await self._conn.execute(
                """UPDATE canonical_goals
                   SET status = ?, updated_at = ?, payload = ?
                   WHERE goal_id = ? AND current_revision = ? AND status = 'active'""",
                (
                    to_status.value,
                    _iso(moved_at),
                    updated.model_dump_json(),
                    goal_id,
                    expected_revision,
                ),
            )
            self._require_won(goal, expected_revision, cursor.rowcount)
            await self._insert_transition(
                goal_id,
                GoalTransitionRecord(
                    goal_id=goal_id,
                    kind=GoalTransitionKind.STATUS,
                    at=moved_at,
                    actor=actor,
                    revision=goal.current_revision,
                    from_status=goal.status,
                    to_status=to_status,
                ),
            )
            await self._conn.commit()
            return updated

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
            goal = await self._require(goal_id)
            require_active(goal)
            if goal.agent_id == agent_id:
                raise GoalTransitionError(
                    f"{goal_id}: {agent_id} already owns this Goal; a reassignment "
                    "must change the owner"
                )
            self._check_revision(goal, expected_revision)
            moved_at = at or _utcnow()
            updated = goal.model_copy(update={"agent_id": agent_id, "updated_at": moved_at})
            cursor = await self._conn.execute(
                """UPDATE canonical_goals
                   SET agent_id = ?, updated_at = ?, payload = ?
                   WHERE goal_id = ? AND current_revision = ? AND status = 'active'""",
                (agent_id, _iso(moved_at), updated.model_dump_json(), goal_id, expected_revision),
            )
            self._require_won(goal, expected_revision, cursor.rowcount)
            await self._insert_transition(
                goal_id,
                GoalTransitionRecord(
                    goal_id=goal_id,
                    kind=GoalTransitionKind.AGENT_REASSIGN,
                    at=moved_at,
                    actor=actor,
                    revision=goal.current_revision,
                    from_agent_id=goal.agent_id,
                    to_agent_id=agent_id,
                ),
            )
            await self._conn.commit()
            return updated

    async def list_goal_revisions(self, goal_id: str) -> list[GoalRevision]:
        async with self._lock:
            await self._require(goal_id)
            cursor = await self._conn.execute(
                "SELECT payload FROM canonical_goal_revisions WHERE goal_id = ? "
                "ORDER BY revision ASC",
                (goal_id,),
            )
            rows = await cursor.fetchall()
            return [GoalRevision.model_validate(json.loads(row[0])) for row in rows]

    async def list_goal_transitions(self, goal_id: str) -> list[GoalTransitionRecord]:
        async with self._lock:
            await self._require(goal_id)
            cursor = await self._conn.execute(
                "SELECT payload FROM canonical_goal_transitions WHERE goal_id = ? ORDER BY seq ASC",
                (goal_id,),
            )
            rows = await cursor.fetchall()
            return [GoalTransitionRecord.model_validate(json.loads(row[0])) for row in rows]

    async def _require(self, goal_id: str) -> Goal:
        goal = await self._get_goal_row(goal_id)
        if goal is None:
            raise GoalNotFound(goal_id)
        return goal

    async def _get_goal_row(self, goal_id: str) -> Goal | None:
        cursor = await self._conn.execute(
            "SELECT payload FROM canonical_goals WHERE goal_id = ?",
            (goal_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Goal.model_validate(json.loads(row[0]))

    @staticmethod
    def _check_revision(goal: Goal, expected_revision: int) -> None:
        if goal.current_revision != expected_revision:
            raise GoalRevisionConflict(goal.goal_id, expected_revision, goal.current_revision)

    @staticmethod
    def _require_won(goal: Goal, expected_revision: int, rowcount: int | None) -> None:
        """The guarded UPDATE must have moved the one row it guarded.

        Under this store's operation lock a zero-rowcount answer is
        unreachable; the guard exists so a second process sharing the file
        gets the contract's refusal — CAS on revision *and* state — instead
        of a quiet overwrite.
        """
        if rowcount != 1:
            raise GoalRevisionConflict(goal.goal_id, expected_revision, goal.current_revision)

    async def _insert_goal(self, goal: Goal, revision: GoalRevision) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_goals
               (goal_id, workspace_id, project_id, agent_id, parent_goal_id,
                status, current_revision, created_at, updated_at, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                goal.goal_id,
                goal.workspace_id,
                goal.project_id,
                goal.agent_id,
                goal.parent_goal_id,
                goal.status.value,
                goal.current_revision,
                _iso(goal.created_at),
                _iso(goal.updated_at),
                goal.model_dump_json(),
            ),
        )
        await self._insert_revision(goal.goal_id, revision)

    async def _insert_revision(self, goal_id: str, revision: GoalRevision) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_goal_revisions (goal_id, revision, created_at, payload)
               VALUES (?, ?, ?, ?)""",
            (goal_id, revision.revision, _iso(revision.created_at), revision.model_dump_json()),
        )

    async def _insert_transition(self, goal_id: str, record: GoalTransitionRecord) -> None:
        cursor = await self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM canonical_goal_transitions WHERE goal_id = ?",
            (goal_id,),
        )
        row = await cursor.fetchone()
        seq = int(row[0]) + 1 if row is not None else 1
        await self._conn.execute(
            """INSERT INTO canonical_goal_transitions (goal_id, seq, at, kind, payload)
               VALUES (?, ?, ?, ?, ?)""",
            (goal_id, seq, _iso(record.at), record.kind.value, record.model_dump_json()),
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["SqliteGoalStore"]
