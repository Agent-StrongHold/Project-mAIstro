"""PostgreSQL audit log."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.security.sentinel.signing import AuditSigner
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

    def __init__(self, pool: asyncpg.Pool, *, signer: AuditSigner | None = None) -> None:
        self._pool = pool
        self.signer = signer or AuditSigner.from_environment()

    async def ensure_schema(self) -> None:
        """Add proof columns to databases created before signed audit records."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS signature TEXT NOT NULL DEFAULT ''"
            )
            await conn.execute(
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS signing_key_id TEXT NOT NULL DEFAULT ''"
            )
            await conn.execute(
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS proof_type TEXT NOT NULL DEFAULT ''"
            )

    async def log(self, entry: AuditEntry) -> None:
        """Sign and record an audit entry."""
        signed = self.signer.sign(entry)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (boundary, user_id, team_id, agent_id,
                    tool_name, verdict, detail, trace_id, request_id,
                   signature, signing_key_id, proof_type)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                entry.boundary,
                entry.user_id,
                getattr(entry, "team_id", ""),
                entry.agent_id,
                getattr(entry, "tool_name", "") or "",
                entry.verdict,
                entry.detail,
                getattr(signed, "trace_id", ""),
                getattr(signed, "request_id", ""),
                signed.signature,
                signed.signing_key_id,
                signed.proof_type,
            )

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
                signature=r.get("signature", ""),
                signing_key_id=r.get("signing_key_id", ""),
                proof_type=r.get("proof_type", ""),
            )
            for r in rows
        ]

    def verify(self, entry: AuditEntry) -> bool:
        """Verify a row returned by this store against its configured key."""
        return self.signer.verify(entry)
