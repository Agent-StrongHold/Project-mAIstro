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

Two cursors live on a schedule and `record_fire` is the one writer of both
(#1199). `last_fired_at` is the *enumeration* cursor — where the next
evaluation starts looking for occurrences — and moves only when an occurrence
was consumed. `next_due_at` is the *due* cursor — when the next evaluation is
worth running at all, which is what `due()` selects on — and moves whenever an
evaluation learns it, including one that found nothing to fire: a schedule
whose first occurrence is next week must not be re-evaluated every tick until
then because its first evaluation left `next_due_at` empty. Passing
`fired_at=None` records the due cursor alone.

`put` writes the definition and only the definition. On a row that already
exists it keeps the cursors `record_fire` has recorded, whatever the supplied
Schedule carries: a definition refresh is read-then-put with an await between
the halves, and a `record_fire` that lands in that gap must not be written
back over by the stale copy (Codex, #1199). A changed recurrence (`cron` or
`timezone`) is the one thing that clears `next_due_at`, because the recorded
due moment was computed under the old rule and `due()` reads an empty cursor
as "evaluate now".

The SQLite store serializes every writer the way the PostgreSQL store's row
lock does: the read and the write happen inside one `BEGIN IMMEDIATE`
critical section, so a tick and a manual fire advancing the same schedule
cannot both read `runs_so_far = 4` and both write `5`, and cannot lose each
other's `last_run_id` or `next_due_at`. That section is a property of the
*connection*, so the store must be the only writer on its connection (the
container opens it one, `Container.schedule_conn`): on a connection shared
with another store, `BEGIN IMMEDIATE` collides with that store's open
transaction, and a rollback here would discard that store's uncommitted work.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.scheduling.model import Schedule

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
        """Insert the schedule, or replace an existing row's definition.

        The fire cursors (`last_fired_at`, `last_run_id`, `runs_so_far`,
        `next_due_at`) and `created_at` of an existing row are kept -- the
        supplied values are what the caller last *read*, and `record_fire`
        may have moved them since. A new recurrence clears `next_due_at`.
        Returns the row as stored, which is the copy a caller should keep.
        """
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
        fired_at: datetime | None,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int | None = None,
        disable: bool = False,
    ) -> Schedule | None:
        """Advance the cursors after an evaluation, and disable on exhaustion.

        `fired_at` is the newest occurrence consumed and becomes the
        enumeration cursor; `None` says no occurrence was consumed, so that
        cursor stays where it is and only `next_due_at` (the due cursor) is
        recorded (#1199). `fires` follows it when omitted: one fire for a
        consumed occurrence, none when nothing was consumed, so a due-cursor
        write can never spend a bounded schedule's run. Implementations
        serialize the read-then-write so two callers advancing one schedule
        cannot lose each other's update.
        """
        ...


def _advance(
    schedule: Schedule,
    *,
    fired_at: datetime | None,
    run_id: str | None,
    next_due_at: datetime | None,
    fires: int | None,
    disable: bool,
) -> Schedule:
    """The cursor advance, shared by every implementation so they cannot drift."""
    if fires is None:
        fires = 0 if fired_at is None else 1
    return schedule.model_copy(
        update={
            "last_fired_at": fired_at if fired_at is not None else schedule.last_fired_at,
            "last_run_id": run_id if run_id is not None else schedule.last_run_id,
            "runs_so_far": schedule.runs_so_far + fires,
            "next_due_at": None if disable else next_due_at,
            "enabled": False if disable else schedule.enabled,
            "updated_at": datetime.now(UTC),
        }
    )


def _merged(stored: Schedule | None, definition: Schedule) -> Schedule:
    """The row `put` writes: the new definition over the recorded cursors.

    Shared by every implementation for the same reason as `_advance`. A row
    that does not exist yet is stored as given, cursors included, so a caller
    importing a schedule with history keeps it.
    """
    if stored is None:
        return definition
    recurrence_changed = (definition.cron, definition.timezone) != (stored.cron, stored.timezone)
    return definition.model_copy(
        update={
            "last_fired_at": stored.last_fired_at,
            "last_run_id": stored.last_run_id,
            "runs_so_far": stored.runs_so_far,
            "next_due_at": None if recurrence_changed else stored.next_due_at,
            "created_at": stored.created_at,
        }
    )


def _is_due(schedule: Schedule, *, now: datetime) -> bool:
    return schedule.enabled and (schedule.next_due_at is None or schedule.next_due_at <= now)


class InMemoryScheduleStore:
    """Process-local store. Loses schedules on restart — tests and dev only."""

    def __init__(self) -> None:
        self._schedules: dict[str, Schedule] = {}

    async def put(self, schedule: Schedule) -> Schedule:
        stored = _merged(self._schedules.get(schedule.schedule_id), schedule)
        self._schedules[schedule.schedule_id] = stored
        return stored

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
        fired_at: datetime | None,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int | None = None,
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
        # One connection, so this orders same-process writers; `BEGIN
        # IMMEDIATE` is what protects a second process sharing this file.
        # Every writer takes it through `_serialized_write` (#1199), for the
        # reason `SqliteProjectScopeStore` gives: SQLite starts a transaction
        # implicitly on a connection's first DML statement, so an unlocked
        # writer left mid-statement would make a locked one's `BEGIN
        # IMMEDIATE` raise "cannot start a transaction within a transaction"
        # the moment their awaits interleaved.
        #
        # The lock is this store's, so the connection must be too: a sibling
        # store paused between its DML and its commit on a shared connection
        # is exactly that unlocked writer, and the rollback below would then
        # discard *its* work (Codex, #1199). The container therefore opens
        # this store its own connection, as it does the session store's.
        self._write_lock = asyncio.Lock()

    @asynccontextmanager
    async def _serialized_write(self) -> AsyncIterator[None]:
        """Take this connection's one write-critical section.

        `BEGIN IMMEDIATE` takes SQLite's write lock before the read rather
        than at the first write, which is what makes `record_fire`'s
        read-then-write one unit instead of two halves another writer can
        land between — the property `PgScheduleStore.record_fire` holds with
        `SELECT ... FOR UPDATE`.
        """
        async with self._write_lock:
            try:
                # BEGIN may reach SQLite before its await is cancelled. It
                # belongs inside the rollback fence, before the next writer
                # can acquire this connection's lock.
                await self._conn.execute("BEGIN IMMEDIATE")
                yield
            except BaseException:
                await self._conn.rollback()
                raise
            await self._resolved_commit()

    async def _resolved_commit(self) -> None:
        """Commit, and learn the commit's outcome before classifying the exit.

        aiosqlite queues `commit()` on its worker thread; cancelling the
        awaiting task does not retract a queued COMMIT. A rollback issued on
        that cancellation would queue *behind* the commit, do nothing, and
        leave the caller believing its write was discarded when it had
        landed (Codex, #1199). So the commit is shielded and waited out:
        cancellation is honoured only once the outcome is known, and a
        rollback is issued only for a commit that actually failed.
        """
        commit = asyncio.ensure_future(self._conn.commit())
        interrupted: asyncio.CancelledError | None = None
        while not commit.done():
            try:
                await asyncio.shield(commit)
            except asyncio.CancelledError as exc:
                interrupted = exc
            except BaseException:
                break  # the commit's own failure; classified below
        try:
            commit.result()
        except BaseException as failure:
            await self._conn.rollback()
            if interrupted is not None:
                # A cancelled task ends in CancelledError, whatever else went
                # wrong on the way out; the commit failure rides along as
                # its cause.
                raise interrupted from failure
            raise
        if interrupted is not None:
            # Committed, then cancelled: the write is durable and the caller
            # still sees the cancellation, as any cancelled task must.
            raise interrupted

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
        async with self._serialized_write():
            # Read and merge inside the critical section: the cursors kept
            # are the ones on disk *now*, not the ones the caller read.
            stored = _merged(await self.get(schedule.schedule_id), schedule)
            await self._upsert(stored)
        return stored

    async def _upsert(self, schedule: Schedule) -> None:
        """The one write, issued only inside `_serialized_write`."""
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

    async def get(self, schedule_id: str) -> Schedule | None:
        async with self._conn.execute(
            "SELECT definition FROM schedules WHERE schedule_id = ?", (schedule_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_schedule(row[0]) if row else None

    async def delete(self, schedule_id: str) -> bool:
        async with self._serialized_write():
            cursor = await self._conn.execute(
                "DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,)
            )
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
        fired_at: datetime | None,
        run_id: str | None,
        next_due_at: datetime | None,
        fires: int | None = None,
        disable: bool = False,
    ) -> Schedule | None:
        """Advance the cursors inside one write-critical section (#1199).

        The read and the write share the `BEGIN IMMEDIATE` transaction, so a
        tick and a manual fire advancing the same schedule queue behind each
        other instead of both reading the same `runs_so_far` and each writing
        it plus one — the lost update the PostgreSQL row lock prevents.
        """
        async with self._serialized_write():
            schedule = await self.get(schedule_id)
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
            await self._upsert(advanced)
            return advanced
