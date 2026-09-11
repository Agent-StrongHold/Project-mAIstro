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


class PgGraphContinuationStore:
    """Durable continuation store beside the canonical spine."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, continuation: GraphContinuation) -> GraphContinuation:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO graph_continuations
                       (run_id, status, project_id, admission_source, created_at, resume_at,
                        version, continuation)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8::text::jsonb)
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
                      SET status = $2, project_id = $3, admission_source = $4,
                          created_at = $5, resume_at = $6, version = $7,
                          continuation = $8::text::jsonb
                    WHERE run_id = $1 AND version < $7
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
        admission_source: str | None = None,
    ) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT run_id FROM graph_continuations
                    WHERE status = $1
                      AND ($2::text IS NULL OR project_id = $2)
                      AND ($3::text IS NULL OR admission_source = $3)
                 ORDER BY created_at ASC, run_id ASC
                    LIMIT $4""",
                status.value,
                project_id,
                admission_source,
                limit,
            )
        return [str(row["run_id"]) for row in rows]

    async def list_due_run_ids(
        self,
        *,
        now: datetime,
        limit: int = 100,
        admission_source: str | None = None,
        after: tuple[datetime, str] | None = None,
    ) -> list[str]:
        """Use indexed ownership and deadline columns for bounded recovery scans."""
        async with self._pool.acquire() as conn:
            params: list[Any] = [
                RunStatus.WAITING.value,
                RunStatus.PAUSED.value,
                RunStatus.RUNNING.value,
                now,
                admission_source,
            ]
            after_sql = ""
            if after is not None:
                after_sql = " AND (resume_at > $6 OR (resume_at = $6 AND run_id > $7))"
                params.extend(after)
            params.append(limit)
            rows = await conn.fetch(
                f"""SELECT run_id FROM graph_continuations
                    WHERE status IN ($1, $2, $3)
                      AND resume_at IS NOT NULL
                      AND resume_at <= $4
                      AND ($5::text IS NULL OR admission_source = $5)
                      {after_sql}
                 ORDER BY resume_at ASC, run_id ASC
                    LIMIT ${len(params)}""",
                *params,
            )
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
        continuation.admission_source,
        continuation.created_at,
        continuation.resume_at,
        continuation.version,
        continuation.model_dump_json(),
    )


__all__ = ["PgGraphContinuationStore"]
