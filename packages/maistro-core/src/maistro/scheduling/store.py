"""Schedule persistence: the protocol, an in-memory store, and a SQLite store.

A schedule that vanishes on restart is the defect this layer exists to close.
The protocol is the seam; the SQLite store makes durability real for the
single-conductor deployment without requiring a database server, and a
Postgres implementation can satisfy the same protocol for deployments that
already run one.

There is deliberately no execution table here. Fires are recorded as a
cursor on the schedule (`last_fired_at`, `last_run_id`, `runs_so_far`) and
the execution itself lives in Run history, so this store never becomes a
second place that believes it knows what is running.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.scheduling.model import Schedule

if TYPE_CHECKING:
    import aiosqlite

__all__ = [
    "InMemoryScheduleStore",
    "ScheduleStore",
    "SqliteScheduleStore",
]


@runtime_checkable
class ScheduleStore(Protocol):
    """Durable home for Schedule definitions and their fire cursors."""

    async def put(self, schedule: Schedule) -> Schedule:
        """Insert or replace a schedule."""
        ...

    async def get(self, schedule_id: str) -> Schedule | None: ...

    async def delete(self, schedule_id: str) -> bool: ...

    async def list_for_project(self, *, workspace_id: str, project_id: str) -> list[Schedule]:
        """Every schedule filed in one Project, enabled or not."""
        ...

    async def due(self, *, now: datetime) -> list[Schedule]:
        """Enabled schedules whose next_due_at has arrived.

        Schedules with no recorded next_due_at are returned too: an unknown
        cursor must be evaluated, never silently treated as not-due.
        """
        ...

    async def record_fire(
        self,
        schedule_id: str,
        *,
        fired_at: datetime,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int = 1,
        disable: bool = False,
    ) -> Schedule | None:
        """Advance the cursor after firing, and disable on exhaustion."""
        ...


def _advance(
    schedule: Schedule,
    *,
    fired_at: datetime,
    run_id: str | None,
    next_due_at: datetime | None,
    fires: int,
    disable: bool,
) -> Schedule:
    """The cursor advance, shared by every implementation so they cannot drift."""
    return schedule.model_copy(
        update={
            "last_fired_at": fired_at,
            "last_run_id": run_id if run_id is not None else schedule.last_run_id,
            "runs_so_far": schedule.runs_so_far + fires,
            "next_due_at": None if disable else next_due_at,
            "enabled": False if disable else schedule.enabled,
            "updated_at": datetime.now(UTC),
        }
    )


def _is_due(schedule: Schedule, *, now: datetime) -> bool:
    return schedule.enabled and (schedule.next_due_at is None or schedule.next_due_at <= now)


class InMemoryScheduleStore:
    """Process-local store. Loses schedules on restart — tests and dev only."""

    def __init__(self) -> None:
        self._schedules: dict[str, Schedule] = {}

    async def put(self, schedule: Schedule) -> Schedule:
        self._schedules[schedule.schedule_id] = schedule
        return schedule

    async def get(self, schedule_id: str) -> Schedule | None:
        return self._schedules.get(schedule_id)

    async def delete(self, schedule_id: str) -> bool:
        return self._schedules.pop(schedule_id, None) is not None

    async def list_for_project(self, *, workspace_id: str, project_id: str) -> list[Schedule]:
        return [
            schedule
            for schedule in self._schedules.values()
            if schedule.workspace_id == workspace_id and schedule.project_id == project_id
        ]

    async def due(self, *, now: datetime) -> list[Schedule]:
        return [s for s in self._schedules.values() if _is_due(s, now=now)]

    async def record_fire(
        self,
        schedule_id: str,
        *,
        fired_at: datetime,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int = 1,
        disable: bool = False,
    ) -> Schedule | None:
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return None
        advanced = _advance(
            schedule,
            fired_at=fired_at,
            run_id=run_id,
            next_due_at=next_due_at,
            fires=fires,
            disable=disable,
        )
        self._schedules[schedule_id] = advanced
        return advanced


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    next_due_at REAL,
    definition TEXT NOT NULL
)
"""


class SqliteScheduleStore:
    """SQLite-backed store: schedules survive a restart of one conductor.

    The definition is stored as JSON with the scope, enabled flag, and
    `next_due_at` lifted into columns, so the due query is an index scan
    rather than a deserialize-everything sweep.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.execute(_SCHEMA)
        # The tick runs this query on every pass; without the index it is a
        # full scan that grows with every schedule ever created.
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules (enabled, next_due_at)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_scope ON schedules (workspace_id, project_id)"
        )
        await self._conn.commit()

    @staticmethod
    def _row_to_schedule(definition: str) -> Schedule:
        return Schedule.model_validate(json.loads(definition))

    async def put(self, schedule: Schedule) -> Schedule:
        await self._conn.execute(
            "INSERT INTO schedules "
            "(schedule_id, workspace_id, project_id, enabled, next_due_at, definition) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(schedule_id) DO UPDATE SET "
            "workspace_id=excluded.workspace_id, project_id=excluded.project_id, "
            "enabled=excluded.enabled, next_due_at=excluded.next_due_at, "
            "definition=excluded.definition",
            (
                schedule.schedule_id,
                schedule.workspace_id,
                schedule.project_id,
                int(schedule.enabled),
                schedule.next_due_at.timestamp() if schedule.next_due_at else None,
                schedule.model_dump_json(),
            ),
        )
        await self._conn.commit()
        return schedule

    async def get(self, schedule_id: str) -> Schedule | None:
        async with self._conn.execute(
            "SELECT definition FROM schedules WHERE schedule_id = ?", (schedule_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_schedule(row[0]) if row else None

    async def delete(self, schedule_id: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,)
        )
        await self._conn.commit()
        return bool(cursor.rowcount)

    async def list_for_project(self, *, workspace_id: str, project_id: str) -> list[Schedule]:
        async with self._conn.execute(
            "SELECT definition FROM schedules WHERE workspace_id = ? AND project_id = ? "
            "ORDER BY schedule_id",
            (workspace_id, project_id),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_schedule(row[0]) for row in rows]

    async def due(self, *, now: datetime) -> list[Schedule]:
        async with self._conn.execute(
            "SELECT definition FROM schedules WHERE enabled = 1 "
            "AND (next_due_at IS NULL OR next_due_at <= ?) ORDER BY schedule_id",
            (now.timestamp(),),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_schedule(row[0]) for row in rows]

    async def record_fire(
        self,
        schedule_id: str,
        *,
        fired_at: datetime,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int = 1,
        disable: bool = False,
    ) -> Schedule | None:
        schedule = await self.get(schedule_id)
        if schedule is None:
            return None
        return await self.put(
            _advance(
                schedule,
                fired_at=fired_at,
                run_id=run_id,
                next_due_at=next_due_at,
                fires=fires,
                disable=disable,
            )
        )
