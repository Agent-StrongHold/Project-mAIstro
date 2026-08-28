"""PostgreSQL graph-continuation store (#44).

The durable twin of `InMemoryGraphContinuationStore`. Same split as the rest of
the convergence: the canonical Run, NodeRuns and Attempts are already rows on
the spine, and this holds only what Graph traversal adds — frontier,
blackboard, routing decisions and the commit history — keyed by the Run it
continues.

The lookup columns are denormalized from that Run on every write so "which
graph runs are paused" is an index scan rather than a walk of every Run in the
database. They are an index, not an authority: assembly reads status back from
the canonical Run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
                       (run_id, status, project_id, created_at, resume_at, version,
                        continuation)
                   VALUES ($1, $2, $3, $4, $5, $6, $7::text::jsonb)
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
                "SELECT continuation FROM graph_continuations WHERE run_id = $1", run_id
            )
        if row is None:
            return None
        return GraphContinuation.model_validate_json(row["continuation"])

    async def update(self, continuation: GraphContinuation) -> GraphContinuation:
        """Write only over a strictly older version.

        The version predicate is in the statement rather than a read followed
        by a write, so two writers racing on one Run cannot both believe they
        won -- the same reason the canonical stores put their fences in SQL.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE graph_continuations
                      SET status = $2, project_id = $3, created_at = $4, resume_at = $5,
                          version = $6, continuation = $7::text::jsonb
                    WHERE run_id = $1 AND version < $6
                RETURNING run_id""",
                *_values(continuation),
            )
            if row is not None:
                return continuation
            stored = await conn.fetchval(
                "SELECT version FROM graph_continuations WHERE run_id = $1", continuation.run_id
            )
        if stored is None:
            raise KeyError(f"no such run: {continuation.run_id!r}")
        raise ValueError(f"version regression: stored={stored} incoming={continuation.version}")

    async def list_run_ids_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        project_id: str | None = None,
    ) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT run_id FROM graph_continuations
                    WHERE status = $1 AND ($2::text IS NULL OR project_id = $2)
                 ORDER BY created_at ASC, run_id ASC
                    LIMIT $3""",
                status.value,
                project_id,
                limit,
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
        continuation.created_at,
        continuation.resume_at,
        continuation.version,
        continuation.model_dump_json(),
    )


__all__ = ["PgGraphContinuationStore"]
