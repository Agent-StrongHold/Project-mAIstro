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

The cursor advance is monotonic and counts idempotently (#1059 review). Two
tickers can evaluate overlapping windows and both reach `record_fire`; the
PostgreSQL row lock and the SQLite serialization order the writes, and
`_advance` decides *under that order* what each write may change: a write for
an occurrence the cursor has already passed moves nothing backward, and an
occurrence passed as `fired` counts toward `max_runs` only if the cursor had
not reached it yet — so a ticker refused by the occurrence claim and the
ticker that won it cannot count one firing twice, while a winner that died
before recording its fire is still counted once, by whoever records it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
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
        fired: Sequence[datetime] = (),
        disable: bool = False,
    ) -> Schedule | None:
        """Advance the cursor after firing, and disable on exhaustion.

        Monotonic: `fired_at`, `run_id` and `next_due_at` are applied only when
        `fired_at` is newer than the stored cursor, so a delayed writer cannot
        move the cursor or the pointer backward over a rival that already
        recorded a later occurrence. `fires` counts unconditionally; `fired`
        names occurrences that count once each, judged against the stored
        cursor under the write, which is what makes counting idempotent across
        tickers that consumed the same occurrence (#1059 review). Reaching
        `max_runs` disables the schedule whether or not `disable` asked for it.
        """
        ...


def _advance(
    schedule: Schedule,
    *,
    fired_at: datetime,
    run_id: str | None,
    next_due_at: datetime | None,
    fires: int,
    disable: bool,
    fired: Sequence[datetime] = (),
) -> Schedule:
    """The cursor advance, shared by every implementation so they cannot drift.

    Called with the row already locked (PostgreSQL) or the write serialized
    (SQLite, in-memory), so `schedule` is the current stored state and the
    comparisons below are what make the advance monotonic and the count
    idempotent (#1059 review):

    - a write whose `fired_at` is not newer than the stored cursor is a
      delayed one — a rival already recorded a later occurrence — and moves
      neither the cursor, nor the pointer, nor the due time backward;
    - each occurrence in `fired` counts once: only if the stored cursor had
      not yet passed it. Two tickers that both consumed the same occurrence
      (one won the claim, one was refused) both pass it here, and the second
      write finds the cursor already on it.

    `max_runs` reached is exhaustion whether the caller asked to disable or
    not; the count is settled here, so the decision belongs here too.
    """
    cursor = schedule.last_fired_at
    runs_so_far = schedule.runs_so_far + fires + _uncounted(cursor, fired)
    update: dict[str, object] = {"runs_so_far": runs_so_far, "updated_at": datetime.now(UTC)}
    if cursor is None or fired_at > cursor:
        update["last_fired_at"] = fired_at
        update["next_due_at"] = next_due_at
        if run_id is not None and run_id != schedule.last_run_id:
            update["last_run_id"] = run_id
    if disable or _reached(schedule.max_runs, runs_so_far):
        update["next_due_at"] = None
        update["enabled"] = False
    return schedule.model_copy(update=update)


def _uncounted(cursor: datetime | None, fired: Sequence[datetime]) -> int:
    """How many of `fired` the stored cursor had not yet passed."""
    return sum(1 for moment in fired if cursor is None or moment > cursor)


def _reached(max_runs: int | None, runs_so_far: int) -> bool:
    return max_runs is not None and runs_so_far >= max_runs


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
        fired: Sequence[datetime] = (),
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
            fired=fired,
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
        fired: Sequence[datetime] = (),
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
                fired=fired,
                disable=disable,
            )
        )
