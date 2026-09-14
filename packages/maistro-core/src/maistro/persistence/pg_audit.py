"""PostgreSQL audit log."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.types.security import AuditEntry

if TYPE_CHECKING:
    import asyncpg


_ALLOWED_FILTER_COLUMNS: frozenset[str] = frozenset(
    {
        "user_id",
        "agent_id",
    }
)


class PgAuditLog:
    """PostgreSQL-backed immutable audit log."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (boundary, user_id, team_id, agent_id,
                    tool_name, verdict, detail, trace_id, request_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                entry.boundary,
                entry.user_id,
                getattr(entry, "team_id", ""),
                entry.agent_id,
                getattr(entry, "tool_name", "") or "",
                entry.verdict,
                entry.detail,
                entry.trace_id,
                entry.request_id,
            )

    async def purge_expired(
        self,
        *,
        before: datetime,
        limit: int = 1_000,
        legal_hold_user_ids: tuple[str, ...] = (),
    ) -> int:
        """Delete a bounded old batch while preserving held principals."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        hold = "" if not legal_hold_user_ids else " AND user_id <> ALL($2::text[])"
        params: tuple[Any, ...]
        if legal_hold_user_ids:
            params = (before.astimezone(UTC), list(legal_hold_user_ids), limit)
            limit_mark = "$3"
        else:
            params = (before.astimezone(UTC), limit)
            limit_mark = "$2"
        query = (
            "DELETE FROM audit_log WHERE id IN (SELECT id FROM audit_log "
            "WHERE timestamp < $1" + hold + " ORDER BY timestamp, id LIMIT " + limit_mark + ")"
        )
        async with self._pool.acquire() as conn, conn.transaction():
            result = await conn.execute(query, *params)
        try:
            return int(result.rsplit(" ", 1)[-1])
        except (ValueError, IndexError):
            return 0

    async def get_entries(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        org_id: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Retrieve audit entries with optional filtering."""
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        filters: list[tuple[str, str]] = []
        if user_id:
            filters.append(("user_id", user_id))
        if agent_id:
            filters.append(("agent_id", agent_id))

        for col, value in filters:
            if col not in _ALLOWED_FILTER_COLUMNS:
                raise ValueError(f"Invalid filter column: {col!r}")
            conditions.append(f"{col} = ${idx}")
            params.append(value)
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"
        params.append(limit)
        query = f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}"  # nosec B608

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            AuditEntry(
                timestamp=r["timestamp"],
                boundary=r.get("boundary", ""),
                user_id=r.get("user_id", ""),
                team_id=r.get("team_id", ""),
                agent_id=r.get("agent_id", ""),
                tool_name=r.get("tool_name"),
                verdict=r.get("verdict", "allowed"),
                detail=r.get("detail", ""),
                trace_id=r.get("trace_id", ""),
                request_id=r.get("request_id", ""),
            )
            for r in rows
        ]
