"""PostgreSQL audit log."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.persistence.audit_pages import (
    AUDIT_PAGE_INDEXES,
    AuditPage,
    make_page,
    page_query,
)
from maistro.security.sentinel.signing import SIGNING_KEY_ENV, AuditSigner
from maistro.types.security import AuditEntry

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("maistro.persistence.audit")


_ALLOWED_FILTER_COLUMNS: frozenset[str] = frozenset(
    {
        "user_id",
        "agent_id",
        "org_id",
    }
)


class PgAuditLog:
    """PostgreSQL-backed immutable audit log."""

    def __init__(self, pool: asyncpg.Pool, *, signer: AuditSigner | None = None) -> None:
        self._pool = pool
        self.signer = signer or AuditSigner.from_environment()
        if self.signer.ephemeral:
            logger.warning(
                "audit_log signing key is process-generated (%s is unset): decisions written "
                "to this durable store will not verify after this process exits",
                SIGNING_KEY_ENV,
            )

    async def ensure_schema(self) -> None:
        """Create or upgrade the audit_log table and its indexes.

        Managed deployments get these tables from Alembic (migration 005 plus
        the org-scope and cursor-index migrations). This mirrors the event
        stores' contract: a Container wired against a database that has not run
        ``alembic upgrade head`` still comes up, and wiring creates the schema
        it needs. ``CREATE TABLE IF NOT EXISTS`` is not serialised on its own,
        so a transaction-scoped advisory lock serialises concurrent bootstrap.
        """
        _SCHEMA = """
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            boundary TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            org_id TEXT,
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
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", 0x6175_6469)
            await conn.execute(_SCHEMA)
            for ddl in (
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS org_id TEXT",
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS signature TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS signing_key_id TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS proof_type TEXT NOT NULL DEFAULT ''",
            ):
                await conn.execute(ddl)
            await conn.execute("UPDATE audit_log SET org_id = '' WHERE org_id IS NULL")
            for statement in (
                "CREATE INDEX IF NOT EXISTS ix_audit_log_timestamp ON audit_log (timestamp)",
                "CREATE INDEX IF NOT EXISTS ix_audit_log_user ON audit_log (user_id, timestamp)",
                "CREATE INDEX IF NOT EXISTS ix_audit_log_agent ON audit_log (agent_id, timestamp)",
                "CREATE INDEX IF NOT EXISTS ix_audit_log_scope ON audit_log (org_id, timestamp)",
            ):
                await conn.execute(statement)
            for name, fields in AUDIT_PAGE_INDEXES.items():
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {name} ON audit_log ({', '.join(fields)})"
                )

    async def log(self, entry: AuditEntry) -> None:
        """Sign and record an audit entry."""
        signed = self.signer.sign(entry)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (boundary, user_id, org_id, team_id, agent_id,
                    tool_name, verdict, detail, trace_id, request_id,
                    signature, signing_key_id, proof_type)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                entry.boundary,
                entry.user_id,
                getattr(entry, "org_id", "") or "",
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

    async def get_page(
        self,
        *,
        org_id: str = "",
        user_id: str | None = None,
        boundary: str | None = None,
        denied: bool | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AuditPage:
        query, params = page_query(
            org_id=org_id,
            user_id=user_id,
            boundary=boundary,
            denied=denied,
            limit=limit,
            cursor=cursor,
            postgres=True,
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return make_page(rows, limit)

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
        idx = 1

        filters: list[tuple[str, str]] = []
        if user_id:
            filters.append(("user_id", user_id))
        if agent_id:
            filters.append(("agent_id", agent_id))
        filters.append(("org_id", org_id))

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
                org_id=r.get("org_id", ""),
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
