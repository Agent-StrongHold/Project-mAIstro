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

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.scheduling.model import Schedule

if TYPE_CHECKING:
    import aiosqlite

__all__ = [
    "FireReservation",
    "InMemoryScheduleStore",
    "ScheduleExhausted",
    "ScheduleStore",
    "SqliteScheduleStore",
]


class ScheduleExhausted(Exception):
    """`reserve_fire` found no run left to claim under `max_runs`."""


@dataclass(frozen=True, slots=True)
class FireReservation:
    """One claimed run, held between `reserve_fire` and `settle_fire` (#1119).

    A manual fire claims its slot *before* the Run exists, so two callers
    racing on the last run cannot both pass an exhaustion check they each
    read from a stale snapshot. The reservation remembers what it changed so
    a release is a real undo: `disabled` says this reservation is what turned
    the schedule off (a release turns it back on), `next_due_at_before` is the
    due cursor the disable cleared, and `stamped_at` is the `updated_at` the
    reservation wrote, so a release restores `updated_at_before` only when no
    other writer has touched the row since.
    """

    schedule_id: str
    fires: int
    disabled: bool
    next_due_at_before: datetime | None
    updated_at_before: datetime
    stamped_at: datetime


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

    async def reserve_fire(
        self, schedule_id: str, *, fires: int = 1
    ) -> tuple[Schedule, FireReservation] | None:
        """Atomically claim `fires` of the remaining runs, before any Run exists.

        Counts the fire and disables on exhaustion, exactly as `record_fire`
        would, but leaves `last_fired_at` and `last_run_id` alone: the
        reservation is a quota decision, not a cursor movement. Raises
        `ScheduleExhausted` when `max_runs` leaves no room; returns None for
        an unknown schedule. The check and the increment happen under the
        same lock, so concurrent callers cannot both take the last run.
        """
        ...

    async def settle_fire(
        self, schedule_id: str, reservation: FireReservation, *, run_id: str | None
    ) -> Schedule | None:
        """Close a reservation: record the Run it produced, or give it back.

        With a `run_id`, the Run exists and `last_run_id` points at it; the
        recurrence cursor (`last_fired_at`, `next_due_at`) is not moved, so an
        occurrence the cron already owes stays owed. With `run_id=None` the
        reservation is released: the count comes back, and a disable this
        reservation caused is undone.
        """
        ...


def _reserve(schedule: Schedule, *, fires: int) -> tuple[Schedule, FireReservation]:
    """The quota claim, shared by every implementation so they cannot drift."""
    runs_so_far = schedule.runs_so_far + fires
    if schedule.max_runs is not None and runs_so_far > schedule.max_runs:
        raise ScheduleExhausted(
            f"schedule {schedule.schedule_id} has used all {schedule.max_runs} of its runs"
        )
    disable = schedule.max_runs is not None and runs_so_far >= schedule.max_runs
    stamped_at = datetime.now(UTC)
    update: dict[str, object] = {"runs_so_far": runs_so_far, "updated_at": stamped_at}
    if disable:
        update["enabled"] = False
        update["next_due_at"] = None
    reservation = FireReservation(
        schedule_id=schedule.schedule_id,
        fires=fires,
        disabled=disable and schedule.enabled,
        next_due_at_before=schedule.next_due_at,
        updated_at_before=schedule.updated_at,
        stamped_at=stamped_at,
    )
    return schedule.model_copy(update=update), reservation


def _settle(schedule: Schedule, reservation: FireReservation, *, run_id: str | None) -> Schedule:
    """Confirm or release a reservation, shared by every implementation."""
    if run_id is not None:
        return schedule.model_copy(update={"last_run_id": run_id, "updated_at": datetime.now(UTC)})
    update: dict[str, object] = {
        "runs_so_far": max(0, schedule.runs_so_far - reservation.fires),
        "updated_at": datetime.now(UTC),
    }
    if reservation.disabled and not schedule.enabled:
        update["enabled"] = True
        update["next_due_at"] = reservation.next_due_at_before
    if schedule.updated_at == reservation.stamped_at:
        # Nobody wrote in between: the release leaves no trace at all.
        update["updated_at"] = reservation.updated_at_before
    return schedule.model_copy(update=update)


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

    async def reserve_fire(
        self, schedule_id: str, *, fires: int = 1
    ) -> tuple[Schedule, FireReservation] | None:
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return None
        # No await between the read and the write: on one event loop the
        # check and the increment are one step, which is the whole guarantee.
        reserved, reservation = _reserve(schedule, fires=fires)
        self._schedules[schedule_id] = reserved
        return reserved, reservation

    async def settle_fire(
        self, schedule_id: str, reservation: FireReservation, *, run_id: str | None
    ) -> Schedule | None:
        schedule = self._schedules.get(schedule_id)
        if schedule is None:
            return None
        settled = _settle(schedule, reservation, run_id=run_id)
        self._schedules[schedule_id] = settled
        return settled


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
        # `reserve_fire`'s read and write are two round trips on one
        # connection; the lock makes them one step for concurrent coroutines,
        # which is what a quota check needs to mean anything.
        self._fire_lock = asyncio.Lock()

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

    async def reserve_fire(
        self, schedule_id: str, *, fires: int = 1
    ) -> tuple[Schedule, FireReservation] | None:
        async with self._fire_lock:
            schedule = await self.get(schedule_id)
            if schedule is None:
                return None
            reserved, reservation = _reserve(schedule, fires=fires)
            await self.put(reserved)
            return reserved, reservation

    async def settle_fire(
        self, schedule_id: str, reservation: FireReservation, *, run_id: str | None
    ) -> Schedule | None:
        async with self._fire_lock:
            schedule = await self.get(schedule_id)
            if schedule is None:
                return None
            return await self.put(_settle(schedule, reservation, run_id=run_id))
