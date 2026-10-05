"""PostgreSQL persistence for the canonical Goal (#1572).

The durable twin of `sqlite_store.py` and of `InMemoryGoalStore`, run against
the same conformance suite. The tables come from Alembic migration ``054`` —
this store creates nothing of its own, so a deployment that has not run
`alembic upgrade head` fails loudly at the first query instead of quietly
keeping Goals in a second schema nobody migrates.

What differs from the reference is not the rules but the concurrency, and it
concentrates in one rule: **mutations are compare-and-set on
``current_revision``.** An in-process lock is correct for the reference and
the SQLite twin (one writer at a time) and means nothing across processes, so
every mutation here is one guarded statement —

    UPDATE ... WHERE goal_id = $1 AND current_revision = $n

— and a zero-rowcount answer is the compare-and-set losing. Two concurrent
writers across two processes both issue the guarded update; the row moves
once, so exactly one of them wins, which is the property the conformance
suite's race leg holds every backend to. Because ``UPDATE n`` alone cannot
say why the guard failed, the loser re-reads the row once: gone means
:class:`GoalNotFound`, still holding ``expected_revision`` means the row was
finalized between read and write (mutation was already refused before the
guard), and anything else is :class:`GoalRevisionConflict` — the same refusal
a stale update gets.

Payloads are JSONB and come back as dicts, because the pool registers a JSON
codec (`maistro.persistence._register_json_codecs`) — read through `model_of`
like every other PG store.
"""

from __future__ import annotations

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
from maistro.runs.evidence_json import json_of, model_of

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

#: The guarded UPDATE's shape, shared by all three mutations. ``$1`` is the
#: goal id and the last parameter is always the ``expected_revision`` the
#: caller holds; the compare-and-set lives in the WHERE, not in a lock. The
#: ``status = 'active'`` arm is the state half of the compare-and-set (#1572):
#: a transition does not move ``current_revision``, so a revision-only guard
#: would let the second of two concurrent transitions overwrite the first.
#: It also closes the finalize-between-read-and-write race for every mutation:
#: a Goal another writer moved to a terminal state matches no rows.
_APPEND_SQL = """UPDATE canonical_goals
                 SET current_revision = $2, updated_at = $3, payload = $4::text::jsonb
                 WHERE goal_id = $1 AND current_revision = $5 AND status = 'active'"""
_TRANSITION_SQL = """UPDATE canonical_goals
                     SET status = $2, updated_at = $3, payload = $4::text::jsonb
                     WHERE goal_id = $1 AND current_revision = $5 AND status = 'active'"""
_REASSIGN_SQL = """UPDATE canonical_goals
                   SET agent_id = $2, updated_at = $3, payload = $4::text::jsonb
                   WHERE goal_id = $1 AND current_revision = $5 AND status = 'active'"""


class PgGoalStore:
    """The PostgreSQL Goal store. One pool, one guarded statement per write."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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
        if parent_goal_id is not None:
            await self._require_scope_parent(parent_goal_id, workspace_id, project_id)
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
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO canonical_goals
                   (goal_id, workspace_id, project_id, agent_id, parent_goal_id,
                    status, current_revision, created_at, updated_at, payload)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::text::jsonb)""",
                goal.goal_id,
                goal.workspace_id,
                goal.project_id,
                goal.agent_id,
                goal.parent_goal_id,
                goal.status.value,
                goal.current_revision,
                goal.created_at,
                goal.updated_at,
                json_of(goal),
            )
            await self._insert_revision(conn, goal.goal_id, revision)
        return goal

    async def get_goal(self, goal_id: str) -> Goal | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM canonical_goals WHERE goal_id = $1", goal_id
            )
        return model_of(Goal, row["payload"]) if row is not None else None

    async def append_revision(
        self,
        goal_id: str,
        draft: GoalRevisionDraft,
        *,
        expected_revision: int,
        created_at: datetime | None = None,
    ) -> Goal:
        goal = await self._require_active(goal_id)
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
        async with self._pool.acquire() as conn, conn.transaction():
            outcome = await conn.execute(
                _APPEND_SQL,
                goal_id,
                updated.current_revision,
                updated.updated_at,
                json_of(updated),
                expected_revision,
            )
            await self._require_won(conn, goal_id, outcome, expected_revision)
            await self._insert_revision(conn, goal_id, revision)
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
        goal = await self._require_active(goal_id)
        self._check_revision(goal, expected_revision)
        if not transition_is_legal(goal.status, to_status):
            raise GoalTransitionError(
                f"{goal_id}: a Goal cannot move from {goal.status.value} to {to_status.value}"
            )
        moved_at = at or _utcnow()
        updated = goal.model_copy(update={"status": to_status, "updated_at": moved_at})
        record = GoalTransitionRecord(
            goal_id=goal_id,
            kind=GoalTransitionKind.STATUS,
            at=moved_at,
            actor=actor,
            revision=goal.current_revision,
            from_status=goal.status,
            to_status=to_status,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            outcome = await conn.execute(
                _TRANSITION_SQL,
                goal_id,
                to_status.value,
                moved_at,
                json_of(updated),
                expected_revision,
            )
            await self._require_won(conn, goal_id, outcome, expected_revision)
            await self._insert_transition(conn, record)
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
        goal = await self._require_active(goal_id)
        if goal.agent_id == agent_id:
            raise GoalTransitionError(
                f"{goal_id}: {agent_id} already owns this Goal; a reassignment "
                "must change the owner"
            )
        self._check_revision(goal, expected_revision)
        moved_at = at or _utcnow()
        updated = goal.model_copy(update={"agent_id": agent_id, "updated_at": moved_at})
        record = GoalTransitionRecord(
            goal_id=goal_id,
            kind=GoalTransitionKind.AGENT_REASSIGN,
            at=moved_at,
            actor=actor,
            revision=goal.current_revision,
            from_agent_id=goal.agent_id,
            to_agent_id=agent_id,
        )
        async with self._pool.acquire() as conn, conn.transaction():
            outcome = await conn.execute(
                _REASSIGN_SQL,
                goal_id,
                agent_id,
                moved_at,
                json_of(updated),
                expected_revision,
            )
            await self._require_won(conn, goal_id, outcome, expected_revision)
            await self._insert_transition(conn, record)
        return updated

    async def list_goal_revisions(self, goal_id: str) -> list[GoalRevision]:
        await self._require(goal_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM canonical_goal_revisions WHERE goal_id = $1 "
                "ORDER BY revision ASC",
                goal_id,
            )
        return [model_of(GoalRevision, row["payload"]) for row in rows]

    async def list_goal_transitions(self, goal_id: str) -> list[GoalTransitionRecord]:
        await self._require(goal_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM canonical_goal_transitions WHERE goal_id = $1 "
                "ORDER BY seq ASC",
                goal_id,
            )
        return [model_of(GoalTransitionRecord, row["payload"]) for row in rows]

    async def _require(self, goal_id: str) -> Goal:
        goal = await self.get_goal(goal_id)
        if goal is None:
            raise GoalNotFound(goal_id)
        return goal

    async def _require_active(self, goal_id: str) -> Goal:
        goal = await self._require(goal_id)
        require_active(goal)
        return goal

    async def _require_scope_parent(
        self, parent_goal_id: str, workspace_id: str, project_id: str
    ) -> None:
        parent = await self.get_goal(parent_goal_id)
        if parent is None or parent.workspace_id != workspace_id or parent.project_id != project_id:
            raise GoalParentInvalid(parent_goal_id)

    @staticmethod
    def _check_revision(goal: Goal, expected_revision: int) -> None:
        if goal.current_revision != expected_revision:
            raise GoalRevisionConflict(goal.goal_id, expected_revision, goal.current_revision)

    async def _require_won(
        self, conn: asyncpg.Connection, goal_id: str, outcome: str, expected_revision: int
    ) -> None:
        """Turn a lost compare-and-set into the refusal the contract names.

        ``outcome`` is asyncpg's ``UPDATE <n>`` tag. One row moved: this
        caller won, and the append-only rows inside this transaction are
        legitimate. Zero rows: another writer moved the pointer between the
        read above and this write, so the caller's write is refused with what
        the store holds now.
        """
        if outcome == "UPDATE 1":
            return
        current = await conn.fetchval(
            "SELECT current_revision FROM canonical_goals WHERE goal_id = $1", goal_id
        )
        raise GoalRevisionConflict(goal_id, expected_revision, int(current or 0))

    async def _insert_revision(
        self, conn: asyncpg.Connection, goal_id: str, revision: GoalRevision
    ) -> None:
        await conn.execute(
            """INSERT INTO canonical_goal_revisions (goal_id, revision, created_at, payload)
               VALUES ($1, $2, $3, $4::text::jsonb)""",
            goal_id,
            revision.revision,
            revision.created_at,
            json_of(revision),
        )

    async def _insert_transition(
        self, conn: asyncpg.Connection, record: GoalTransitionRecord
    ) -> None:
        seq: int = await conn.fetchval(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM canonical_goal_transitions WHERE goal_id = $1",
            record.goal_id,
        )
        await conn.execute(
            """INSERT INTO canonical_goal_transitions (goal_id, seq, at, kind, payload)
               VALUES ($1, $2, $3, $4, $5::text::jsonb)""",
            record.goal_id,
            seq,
            record.at,
            record.kind.value,
            json_of(record),
        )


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["PgGoalStore"]
