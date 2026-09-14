"""SQLite-backed audit log (homelab/single-instance deployments)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.types.security import AuditEntry

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    boundary TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    org_id TEXT NOT NULL DEFAULT '',
    team_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT,
    verdict TEXT NOT NULL DEFAULT 'allowed',
    detail TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT ''
)
"""

_ALLOWED_FILTER_COLUMNS: frozenset[str] = frozenset(
    {
        "user_id",
        "agent_id",
        "org_id",
    }
)


class SqliteAuditLog:
    """SQLite-backed immutable audit log implementing the same protocol as PgAuditLog."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create or upgrade the audit_log table and its scope index.

        SQLite has no ``ADD COLUMN IF NOT EXISTS``. Inspecting the table keeps
        existing homelab databases readable while making the empty string an
        explicit representation for legacy system/unscoped entries.
        """
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(audit_log)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "org_id" not in columns:
            await self._conn.execute(
                "ALTER TABLE audit_log ADD COLUMN org_id TEXT NOT NULL DEFAULT ''"
            )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_audit_log_scope ON audit_log (org_id, timestamp)"
        )
        await self._conn.commit()

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        await self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, boundary, user_id, org_id, team_id, agent_id,
                tool_name, verdict, detail, trace_id, request_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.timestamp.isoformat(),
                entry.boundary,
                entry.user_id,
                getattr(entry, "org_id", "") or "",
                getattr(entry, "team_id", ""),
                entry.agent_id,
                getattr(entry, "tool_name", "") or "",
                entry.verdict,
                entry.detail,
                entry.trace_id,
                entry.request_id,
            ),
        )
        await self._conn.commit()

    async def get_entries(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        org_id: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Retrieve audit entries with optional filtering.

        ``org_id`` is always an exact SQL predicate. The empty string is the
        explicit system/unscoped scope and therefore reads only system rows;
        this adapter never turns an omitted scope into an all-organization
        read. A caller that needs a tenant read must pass its non-empty org id.
        """
        if org_id is None:
            raise ValueError("org_id cannot be None; pass '' for an unscoped read")

        conditions: list[str] = []
        params: list[Any] = []

        filters: list[tuple[str, str]] = []
        if user_id:
            filters.append(("user_id", user_id))
        if agent_id:
            filters.append(("agent_id", agent_id))
        filters.append(("org_id", org_id))

        for col, value in filters:
            if col not in _ALLOWED_FILTER_COLUMNS:
                raise ValueError(f"Invalid filter column: {col!r}")
            conditions.append(f"{col} = ?")  # nosec B608 - col is allowlist-validated
            params.append(value)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        query = (
            f"SELECT timestamp, boundary, user_id, org_id, team_id, agent_id, tool_name, "
            f"verdict, detail, trace_id, request_id FROM audit_log "
            f"WHERE {where} ORDER BY timestamp DESC LIMIT ?"  # nosec B608
        )

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()

        from datetime import datetime

        return [
            AuditEntry(
                timestamp=datetime.fromisoformat(r[0]),
                boundary=r[1] or "",
                user_id=r[2] or "",
                org_id=r[3] or "",
                team_id=r[4] or "",
                agent_id=r[5] or "",
                tool_name=r[6],
                verdict=r[7] or "allowed",
                detail=r[8] or "",
                trace_id=r[9] or "",
                request_id=r[10] or "",
            )
            for r in rows
        ]
