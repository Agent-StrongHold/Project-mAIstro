"""PostgreSQL graph-continuation store (#44).

The durable twin of `InMemoryGraphContinuationStore`. Same split as the rest of
the convergence: the canonical Run, NodeRuns and Attempts are already rows on
the spine, and this holds only what Graph traversal adds — frontier,
blackboard, routing decisions and the commit history — keyed by the Run it
continues.

The lookup columns are denormalized from that Run on every write so recovery
queries are index scans rather than walks of every Run in the database. They
are an index, not an authority: assembly reads status back from the canonical
Run.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from maistro.runs.evidence_json import decode_payload
from maistro.runs.model import RunStatus

from .continuation import GraphContinuation

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg


def _list_run_ids_by_status_query(
    status_value: str,
    *,
    project_id: str | None = None,
    after: tuple[datetime, str] | None = None,
    limit: int,
) -> tuple[str, list[Any]]:
    """The exact SQL `list_run_ids_by_status` runs, as a module function so a
    test can `EXPLAIN` the query that actually ships — the same reason
    `pg_store` exposes `_list_by_status_query`.

    Two literal statements rather than one `$2 IS NULL OR project_id = $2`:
    an OR whose first arm does not reference the indexed column can never
    become an index condition, so the single-statement shape degraded to a
    scan-plus-sort even where `ix_graph_continuations_status_created`
    (migration 057) carries the exact `(status, created_at, run_id)` order
    (#863). Without a project, `status` equality alone yields the ordering;
    with one, `project_id` filters inline over the same ordered scan —
    bounded by that status's rows, which is the population the query names
    anyway. `status = $1` stays a parameter on purpose: the serving index is
    unconditional, so a generic prepared plan needs no predicate proof.
    """
    if project_id is None:
        sql = "SELECT run_id FROM graph_continuations WHERE status = $1"
        params: list[Any] = [status_value]
    else:
        sql = "SELECT run_id FROM graph_continuations WHERE status = $1 AND project_id = $2"
        params = [status_value, project_id]
    if after is not None:
        after_created, after_run_id = after
        cursor_param = len(params) + 1
        sql += f" AND (created_at, run_id) > (${cursor_param}, ${cursor_param + 1})"
        params.extend([after_created, after_run_id])
    sql += f" ORDER BY created_at ASC, run_id ASC LIMIT ${len(params) + 1}"
    params.append(limit)
    return sql, params


def _list_hitl_paused_run_ids_query(
    *,
    project_id: str | None,
    after: tuple[datetime, str] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """The exact SQL `list_hitl_paused_run_ids` runs, exposed for the same
    reason `_list_run_ids_by_status_query` is: a test can `EXPLAIN` the query
    that ships.

    The same two-literal-statements shape: `ix_graph_continuations_hitl_paused`
    (migration 059) carries `(status, has_hitl_pause, created_at, run_id)`, and
    an OR'd `$2 IS NULL OR project_id = $2` arm would degrade it to a
    scan-plus-sort exactly as it would the status query above.
    """
    if project_id is None:
        sql = "SELECT run_id FROM graph_continuations WHERE status = $1 AND has_hitl_pause"
        params: list[Any] = [RunStatus.PAUSED.value]
    else:
        sql = (
            "SELECT run_id FROM graph_continuations "
            "WHERE status = $1 AND has_hitl_pause AND project_id = $2"
        )
        params = [RunStatus.PAUSED.value, project_id]
    if after is not None:
        after_created, after_run_id = after
        cursor_param = len(params) + 1
        sql += f" AND (created_at, run_id) > (${cursor_param}, ${cursor_param + 1})"
        params.extend([after_created, after_run_id])
    sql += f" ORDER BY created_at ASC, run_id ASC LIMIT ${len(params) + 1}"
    params.append(limit)
    return sql, params


class PgGraphContinuationStore:
    """Durable continuation store beside the canonical spine."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, continuation: GraphContinuation) -> GraphContinuation:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO graph_continuations
                       (run_id, status, project_id, created_at, resume_at,
                        hitl_deadline_at, has_hitl_pause, version, continuation)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::text::jsonb)
                   ON CONFLICT (run_id) DO NOTHING
                   RETURNING run_id""",
                *_values(continuation),
            )
        if row is None:
            raise ValueError(f"run_id collision: {continuation.run_id!r}")
        return continuation

    async def get(self, run_id: str) -> GraphContinuation | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT continuation FROM graph_continuations WHERE run_id = $1",
                run_id,
            )
        if row is None:
            return None
        return GraphContinuation.model_validate(decode_payload(row["continuation"]))

    async def update(self, continuation: GraphContinuation) -> GraphContinuation:
        """Write only over a strictly older version."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE graph_continuations
                      SET status = $2, project_id = $3, created_at = $4, resume_at = $5,
                          hitl_deadline_at = $6, has_hitl_pause = $7, version = $8,
                          continuation = $9::text::jsonb
                    WHERE run_id = $1 AND version < $8
                RETURNING run_id""",
                *_values(continuation),
            )
            if row is not None:
                return continuation
            stored = await conn.fetchval(
                "SELECT version FROM graph_continuations WHERE run_id = $1",
                continuation.run_id,
            )
        if stored is None:
            raise KeyError(f"no such run: {continuation.run_id!r}")
        raise ValueError(f"version regression: stored={stored} incoming={continuation.version}")

    async def delete(self, run_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM graph_continuations WHERE run_id = $1",
                run_id,
            )
        return str(result) != "DELETE 0"

    async def list_run_ids_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        """Continuation ids in ``status``, oldest first, per project when named."""
        sql, params = _list_run_ids_by_status_query(
            status.value,
            project_id=project_id,
            after=None if after is None else (datetime.fromisoformat(after[0]), after[1]),
            limit=limit,
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [str(row["run_id"]) for row in rows]

    async def list_due_run_ids(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        """Use persisted wait/claim deadlines to find bounded recovery candidates."""
        sql = """SELECT run_id FROM graph_continuations
                    WHERE status IN ($1, $2, $3)
                      AND resume_at IS NOT NULL
                      AND resume_at <= $4"""
        params: list[Any] = [
            RunStatus.WAITING.value,
            RunStatus.PAUSED.value,
            RunStatus.RUNNING.value,
            now,
        ]
        if after is not None:
            after_resume_at, after_run_id = after
            cursor_param = len(params) + 1
            sql += f" AND (resume_at, run_id) > (${cursor_param}, ${cursor_param + 1})"
            params.extend([datetime.fromisoformat(after_resume_at), after_run_id])
        sql += f" ORDER BY resume_at ASC, run_id ASC LIMIT ${len(params) + 1}"
        params.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [str(row["run_id"]) for row in rows]

    async def list_hitl_due_run_ids(self, *, now: datetime, limit: int = 100) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT run_id FROM graph_continuations
                    WHERE status = $1
                      AND hitl_deadline_at IS NOT NULL
                      AND hitl_deadline_at <= $2
                 ORDER BY hitl_deadline_at ASC, run_id ASC
                    LIMIT $3""",
                RunStatus.PAUSED.value,
                now,
                limit,
            )
        return [str(row["run_id"]) for row in rows]

    async def list_hitl_paused_run_ids(
        self,
        *,
        limit: int = 100,
        project_id: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[str]:
        """Paused continuations holding a human pause, oldest first (#1109)."""
        sql, params = _list_hitl_paused_run_ids_query(
            project_id=project_id,
            after=None if after is None else (datetime.fromisoformat(after[0]), after[1]),
            limit=limit,
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [str(row["run_id"]) for row in rows]

    async def list_run_ids_for_project(self, project_id: str, *, limit: int = 25) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT run_id FROM graph_continuations
                    WHERE project_id = $1
                 ORDER BY created_at DESC, run_id DESC
                    LIMIT $2""",
                project_id,
                limit,
            )
        return [str(row["run_id"]) for row in rows]


def _values(continuation: GraphContinuation) -> tuple[Any, ...]:
    return (
        continuation.run_id,
        continuation.status.value,
        continuation.project_id,
        continuation.created_at,
        continuation.resume_at,
        continuation.hitl_deadline_at,
        continuation.has_hitl_pause,
        continuation.version,
        continuation.model_dump_json(),
    )


__all__ = ["PgGraphContinuationStore"]
