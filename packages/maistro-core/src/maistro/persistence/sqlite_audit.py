"""SQLite-backed audit log (homelab/single-instance deployments)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.persistence.audit_pages import AUDIT_PAGE_INDEXES, AuditPage, make_page, page_query
from maistro.security.sentinel.signing import SIGNING_KEY_ENV, AuditSigner
from maistro.sqlite_schema import serialized_schema_upgrade
from maistro.types.security import AuditEntry

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger("maistro.persistence.audit")

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
        "org_id",
    }
)


def _proof_from_row(row: Any) -> tuple[str, str, str]:
    """Normalize the ADR-073 proof columns persisted alongside a decision."""
    return (row[11] or "", row[12] or "", row[13] or "")


def _build_filter_clause(
    *, user_id: str | None, agent_id: str | None, org_id: str
) -> tuple[str, list[Any]]:
    """Build the exact-scope predicates and bound values for an audit read."""
    filters = tuple(
        (column, value)
        for column, value in (
            ("user_id", user_id),
            ("agent_id", agent_id),
            ("org_id", org_id),
        )
        if value is not None and (column == "org_id" or value)
    )
    invalid = next(
        (column for column, _value in filters if column not in _ALLOWED_FILTER_COLUMNS), None
    )
    if invalid is not None:
        raise ValueError(f"Invalid filter column: {invalid!r}")
    return (
        " AND ".join(f"{column} = ?" for column, _value in filters),
        [value for _column, value in filters],
    )


class SqliteAuditLog:
    """SQLite-backed immutable audit log implementing the same protocol as PgAuditLog."""

    def __init__(self, conn: aiosqlite.Connection, *, signer: AuditSigner | None = None) -> None:
        self._conn = conn
        self.signer = signer or AuditSigner.from_environment()
        if self.signer.ephemeral:
            logger.warning(
                "audit_log signing key is process-generated (%s is unset): decisions written "
                "to this durable store will not verify after this process exits",
                SIGNING_KEY_ENV,
            )

    async def ensure_schema(self) -> None:
        """Create or upgrade the audit_log table, its scope and page indexes.

        SQLite has no ``ADD COLUMN IF NOT EXISTS``. Inspecting the table keeps
        existing homelab databases readable while making the empty string an
        explicit representation for legacy system/unscoped entries, and adds
        the ADR-073 proof columns to databases created before signed records.
        The whole read-then-DDL sequence runs under the shared schema-upgrade
        lock so concurrent processes cannot both decide a column is absent.
        """
        async with serialized_schema_upgrade(self._conn):
            await self._conn.execute(_SCHEMA)
            cursor = await self._conn.execute("PRAGMA table_info(audit_log)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "org_id" not in columns:
                await self._conn.execute(
                    "ALTER TABLE audit_log ADD COLUMN org_id TEXT NOT NULL DEFAULT ''"
                )
            for name in ("signature", "signing_key_id", "proof_type"):
                if name not in columns:
                    await self._conn.execute(
                        f"ALTER TABLE audit_log ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"  # nosec B608
                    )
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_audit_log_scope ON audit_log (org_id, timestamp)"
            )
            # Retention's purge scans oldest-first across every scope, so it
            # needs the timestamp-led index the org-led page indexes reverse.
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log (timestamp, id)"
            )

            for name, fields in AUDIT_PAGE_INDEXES.items():
                await self._conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {name} ON audit_log ({', '.join(fields)})"
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
        )
        async with self._conn.execute(query, params) as result:
            names = [column[0] for column in result.description]
            rows = [dict(zip(names, row, strict=True)) for row in await result.fetchall()]
        return make_page(rows, limit)

    async def log(self, entry: AuditEntry) -> None:
        """Sign and record an audit entry."""
        signed = self.signer.sign(entry)
        await self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, boundary, user_id, org_id, team_id, agent_id,
                tool_name, verdict, detail, trace_id, request_id,
                signature, signing_key_id, proof_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                getattr(signed, "timestamp", datetime.now(UTC)).isoformat(),
                signed.boundary,
                signed.user_id,
                getattr(signed, "org_id", "") or "",
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

    async def purge_expired(
        self,
        *,
        before: datetime,
        limit: int = 1_000,
        legal_hold_user_ids: tuple[str, ...] = (),
    ) -> int:
        """Delete an old bounded batch without crossing a legal hold.

        The audit log is append-only evidence with a bounded lifetime (its
        policy, including legal hold, is the importing product's per the #325
        owner decision — this is the mechanism, not the policy). The delete
        runs as one transaction of at most ``limit`` rows ordered oldest-first,
        so a replica's lock hold is bounded and a crash mid-purge commits
        nothing: the next call re-selects the same rows, which makes retries
        and concurrent replicas idempotent.
        """
        if limit <= 0:
            raise ValueError("limit must be positive")
        hold_sql = ""
        params: list[Any] = [before.astimezone(UTC).isoformat()]
        if legal_hold_user_ids:
            marks = ",".join("?" for _ in legal_hold_user_ids)
            hold_sql = f" AND user_id NOT IN ({marks})"  # nosec B608 - values bound, identifiers are literal ?
            params.extend(legal_hold_user_ids)
        params.append(limit)
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await self._conn.execute(
                "DELETE FROM audit_log WHERE id IN (SELECT id FROM audit_log "
                "WHERE timestamp < ?" + hold_sql + " ORDER BY timestamp, id LIMIT ?)",
                params,
            )
            await self._conn.commit()
            return max(cursor.rowcount, 0)
        except BaseException:
            await self._conn.rollback()
            raise

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

        where, params = _build_filter_clause(
            user_id=user_id,
            agent_id=agent_id,
            org_id=org_id,
        )
        where = where or "1=1"
        params.append(limit)
        query = (
            f"SELECT timestamp, boundary, user_id, org_id, team_id, agent_id, tool_name, "
            f"verdict, detail, trace_id, request_id, signature, signing_key_id, proof_type "
            f"FROM audit_log "
            f"WHERE {where} ORDER BY timestamp DESC LIMIT ?"  # nosec B608
        )

        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()

        entries: list[AuditEntry] = []
        for r in rows:
            signature, signing_key_id, proof_type = _proof_from_row(r)
            entries.append(
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
                    signature=signature,
                    signing_key_id=signing_key_id,
                    proof_type=proof_type,
                )
            )
        return entries

    def verify(self, entry: AuditEntry) -> bool:
        """Verify a row returned by this store against its configured key."""
        return self.signer.verify(entry)
