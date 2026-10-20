"""SQLite-backed audit log (homelab/single-instance deployments)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from maistro.security.sentinel.integrity import DecisionSignature
from maistro.types.security import AuditEntry, Violation

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
    request_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    principal_id TEXT NOT NULL DEFAULT '',
    policy_snapshot TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '',
    inputs_hash TEXT NOT NULL DEFAULT '',
    signature TEXT,
    signature_key_id TEXT,
    signature_algorithm TEXT,
    signature_public_key TEXT,
    violations TEXT NOT NULL DEFAULT '[]'
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

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the table and add integrity columns to older homelab DBs."""
        await self._conn.execute(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(audit_log)")
        existing = {row[1] for row in await cursor.fetchall()}
        additions = {
            "action": "TEXT NOT NULL DEFAULT ''",
            "org_id": "TEXT NOT NULL DEFAULT ''",
            "principal_id": "TEXT NOT NULL DEFAULT ''",
            "policy_snapshot": "TEXT NOT NULL DEFAULT ''",
            "payload": "TEXT NOT NULL DEFAULT ''",
            "inputs_hash": "TEXT NOT NULL DEFAULT ''",
            "signature": "TEXT",
            "signature_key_id": "TEXT",
            "signature_algorithm": "TEXT",
            "signature_public_key": "TEXT",
            "violations": "TEXT NOT NULL DEFAULT '[]'",
        }
        for name, definition in additions.items():
            if name not in existing:
                await self._conn.execute(f"ALTER TABLE audit_log ADD COLUMN {name} {definition}")
        await self._conn.commit()

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        await self._conn.execute(
            """INSERT INTO audit_log
               (timestamp, boundary, user_id, org_id, team_id, agent_id,
                tool_name, verdict, detail, trace_id, request_id, action,
                principal_id, policy_snapshot, payload, inputs_hash, signature,
                signature_key_id, signature_algorithm, signature_public_key, violations)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.timestamp.isoformat(),
                entry.boundary,
                entry.user_id,
                getattr(entry, "org_id", ""),
                getattr(entry, "team_id", ""),
                entry.agent_id,
                getattr(entry, "tool_name", "") or "",
                entry.verdict,
                entry.detail,
                getattr(entry, "trace_id", ""),
                getattr(entry, "request_id", ""),
                getattr(entry, "action", ""),
                getattr(entry, "principal_id", "") or entry.user_id,
                getattr(entry, "policy_snapshot", ""),
                getattr(entry, "payload", ""),
                getattr(entry, "inputs_hash", ""),
                getattr(getattr(entry, "integrity", None), "signature", None),
                getattr(getattr(entry, "integrity", None), "key_id", None),
                getattr(getattr(entry, "integrity", None), "algorithm", None),
                getattr(getattr(entry, "integrity", None), "public_key", None),
                json.dumps(
                    [
                        {
                            "boundary": v.boundary,
                            "rule": v.rule,
                            "severity": v.severity,
                            "detail": v.detail,
                            "repair_action": v.repair_action,
                        }
                        for v in getattr(entry, "violations", ())
                    ],
                    sort_keys=True,
                ),
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
            f"SELECT timestamp, boundary, user_id, org_id, team_id, agent_id, tool_name, "
            f"verdict, detail, trace_id, request_id, action, principal_id, "
            f"policy_snapshot, payload, signature, signature_key_id, "
            f"signature_algorithm, signature_public_key, violations, inputs_hash FROM audit_log "
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
                action=r[11] or "",
                principal_id=r[12] or "",
                policy_snapshot=r[13] or "",
                payload=r[14] or "",
                inputs_hash=r[20] or "",
                integrity=(
                    DecisionSignature(
                        key_id=r[16], algorithm=r[17], signature=r[15], public_key=r[18]
                    )
                    if r[15] and r[16] and r[17] and r[18]
                    else None
                ),
                violations=tuple(Violation(**item) for item in json.loads(r[19] or "[]")),
            )
            for r in rows
        ]
