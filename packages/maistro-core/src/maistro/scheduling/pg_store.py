"""PostgreSQL Schedule store (#231).

The durable twin of `SqliteScheduleStore`, and the one that makes a schedule
shareable between processes. SQLite's docstring says it plainly — "schedules
survive a restart of one conductor" — and its `record_fire` is a read, a
model copy, and a write, which is correct for one writer and wrong for two.

`record_fire` here takes a row lock and advances inside one transaction, so two
scheduler replicas ticking the same second cannot both read `runs_so_far = 4`
and both write `5`. That matters beyond the counter: `max_runs` exhaustion is
computed from it, so a lost update is a schedule that fires more times than it
was configured for.

The cursor advance itself still goes through `_advance`, shared with every
other implementation so the three backends cannot drift on what "fired" means.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.runs.evidence_json import json_of, model_of
from maistro.scheduling.model import Schedule
from maistro.scheduling.store import _advance

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


def _schedule_of(payload: Any) -> Schedule:
    return model_of(Schedule, payload)


class PgScheduleStore:
    """Durable, shareable home for Schedule definitions and their fire cursors."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def put(self, schedule: Schedule) -> Schedule:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO schedules
                       (schedule_id, workspace_id, project_id, enabled, next_due_at, payload)
                   VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)
                   ON CONFLICT (schedule_id) DO UPDATE
                       SET workspace_id = EXCLUDED.workspace_id,
                           project_id   = EXCLUDED.project_id,
                           enabled      = EXCLUDED.enabled,
                           next_due_at  = EXCLUDED.next_due_at,
                           payload      = EXCLUDED.payload""",
                schedule.schedule_id,
                schedule.workspace_id,
                schedule.project_id,
                schedule.enabled,
                schedule.next_due_at,
                json_of(schedule),
            )
        return schedule

    async def get(self, schedule_id: str) -> Schedule | None:
        async with self._pool.acquire() as conn:
            payload = await conn.fetchval(
                "SELECT payload FROM schedules WHERE schedule_id = $1", schedule_id
            )
        return _schedule_of(payload) if payload is not None else None

    async def delete(self, schedule_id: str) -> bool:
        """True when a row was removed.

        asyncpg reports a command tag ("DELETE 1"), not a rowcount, so the
        count is the last field of that string.
        """
        async with self._pool.acquire() as conn:
            tag: str = await conn.execute(
                "DELETE FROM schedules WHERE schedule_id = $1", schedule_id
            )
        return tag.rsplit(" ", 1)[-1] != "0"

    async def list_for_project(self, *, workspace_id: str, project_id: str) -> list[Schedule]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM schedules
                   WHERE workspace_id = $1 AND project_id = $2
                   ORDER BY schedule_id""",
                workspace_id,
                project_id,
            )
        return [_schedule_of(row["payload"]) for row in rows]

    async def due(self, *, now: datetime) -> list[Schedule]:
        """Enabled schedules whose cursor has arrived, plus those with none.

        `next_due_at IS NULL` is included deliberately, matching the protocol:
        an unknown cursor must be evaluated. A schedule written by `put` before
        its first tick has one, and treating it as not-due would mean a brand
        new schedule never fires.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT payload FROM schedules
                   WHERE enabled AND (next_due_at IS NULL OR next_due_at <= $1)
                   ORDER BY schedule_id""",
                now,
            )
        return [_schedule_of(row["payload"]) for row in rows]

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
        """Advance the cursor under a row lock, so a concurrent tick cannot lose it."""
        async with self._pool.acquire() as conn, conn.transaction():
            payload = await conn.fetchval(
                "SELECT payload FROM schedules WHERE schedule_id = $1 FOR UPDATE",
                schedule_id,
            )
            if payload is None:
                return None
            advanced = _advance(
                _schedule_of(payload),
                fired_at=fired_at,
                run_id=run_id,
                next_due_at=next_due_at,
                fires=fires,
                disable=disable,
            )
            await conn.execute(
                """UPDATE schedules
                       SET enabled = $2, next_due_at = $3, payload = $4::text::jsonb
                   WHERE schedule_id = $1""",
                schedule_id,
                advanced.enabled,
                advanced.next_due_at,
                json_of(advanced),
            )
        return advanced


__all__ = ["PgScheduleStore"]
