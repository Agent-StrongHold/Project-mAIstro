"""SQLite-backed audit log (homelab/single-instance deployments)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.security.sentinel.signing import AuditSigner
from maistro.types.security import AuditEntry

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    boundary TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    team_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT,
    verdict TEXT NOT NULL DEFAULT 'allowed',
    detail TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    signature TEXT NOT NULL DEFAULT '',
    signing_key_id TEXT NOT NULL DEFAULT '',
    proof_type TEXT NOT NULL DEFAULT ''
)
"""

_ALLOWED_FILTER_COLUMNS: frozenset[str] = frozenset(
    {
        "user_id",
        "agent_id",
    }
)


class SqliteAuditLog:
    """SQLite-backed immutable audit log implementing the same protocol as PgAuditLog."""

    def __init__(self, conn: aiosqlite.Connection, *, signer: AuditSigner | None = None) -> None:
        self._conn = conn
        self.signer = signer or AuditSigner.from_environment()

    async def ensure_schema(self) -> None:
        """Create the audit_log table and upgrade pre-signature databases."""
        await self._conn.execute(_SCHEMA)
        columns = {
            row[1]
            for row in await (await self._conn.execute("PRAGMA table_info(audit_log)")).fetchall()
        }
        for name in ("signature", "signing_key_id", "proof_type"):
            if name not in columns:
                await self._conn.execute(
                    f"ALTER TABLE audit_log ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"  # nosec B608
                )
        await self._conn.commit()

    async def log(self, entry: AuditEntry) -> None:
        """Sign and record an audit entry."""
        signed = self.signer.sign(entry)
        await self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, boundary, user_id, team_id, agent_id,
                tool_name, verdict, detail, trace_id, request_id,
                signature, signing_key_id, proof_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                getattr(signed, "timestamp", datetime.now(UTC)).isoformat(),
                signed.boundary,
                signed.user_id,
                getattr(signed, "team_id", ""),
                signed.agent_id,
                getattr(signed, "tool_name", "") or "",
                signed.verdict,
                signed.detail,
                getattr(signed, "trace_id", ""),
                getattr(signed, "request_id", ""),
                signed.signature,
                signed.signing_key_id,
                signed.proof_type,
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
        """Retrieve audit entries with optional filtering."""
        conditions: list[str] = []
        params: list[Any] = []

        filters: list[tuple[str, str]] = []
        if user_id:
            filters.append(("user_id", user_id))
        if agent_id:
            filters.append(("agent_id", agent_id))

        for col, value in filters:
            if col not in _ALLOWED_FILTER_COLUMNS:
                raise ValueError(f"Invalid filter column: {col!r}")
            conditions.append(f"{col} = ?")  # nosec B608 - col is allowlist-validated
            params.append(value)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        query = (
            f"SELECT timestamp, boundary, user_id, team_id, agent_id, tool_name, "
            f"verdict, detail, trace_id, request_id, signature, signing_key_id, proof_type "
            f"FROM audit_log "
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
                team_id=r[3] or "",
                agent_id=r[4] or "",
                tool_name=r[5],
                verdict=r[6] or "allowed",
                detail=r[7] or "",
                trace_id=r[8] or "",
                request_id=r[9] or "",
                signature=r[10] or "",
                signing_key_id=r[11] or "",
                proof_type=r[12] or "",
            )
            for r in rows
        ]

    def verify(self, entry: AuditEntry) -> bool:
        """Verify a row returned by this store against its configured key."""
        return self.signer.verify(entry)
