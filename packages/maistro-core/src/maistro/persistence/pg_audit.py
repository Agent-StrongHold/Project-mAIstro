"""PostgreSQL audit log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.security.sentinel.integrity import DecisionSignature
from maistro.types.security import AuditEntry, Violation

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

    @staticmethod
    def _signed_timestamp(entry: AuditEntry) -> datetime:
        """Store the timestamp the signature covers, not the insert time.

        ``audit_log.timestamp`` has a ``now()`` default. Leaving the column to
        that default would silently break verification: every reloaded row would
        differ from the bytes that were signed, no matter how intact the rest of
        the record is.
        """
        timestamp = entry.timestamp
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=UTC)
        return timestamp

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (boundary, user_id, org_id, team_id, agent_id,
                    tool_name, verdict, detail, trace_id, request_id, action,
                    principal_id, policy_snapshot, payload, signature,
                    signature_key_id, signature_algorithm, signature_public_key, violations,
                    inputs_hash, timestamp)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)""",
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
                getattr(entry, "inputs_hash", ""),
                self._signed_timestamp(entry),
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
                org_id=r.get("org_id", ""),
                team_id=r.get("team_id", ""),
                agent_id=r.get("agent_id", ""),
                tool_name=r.get("tool_name"),
                verdict=r.get("verdict", "allowed"),
                detail=r.get("detail", ""),
                trace_id=r.get("trace_id", ""),
                request_id=r.get("request_id", ""),
                action=r.get("action", ""),
                principal_id=r.get("principal_id", ""),
                policy_snapshot=r.get("policy_snapshot", ""),
                payload=r.get("payload", ""),
                inputs_hash=r.get("inputs_hash", ""),
                integrity=(
                    DecisionSignature(
                        key_id=r["signature_key_id"],
                        algorithm=r["signature_algorithm"],
                        signature=r["signature"],
                        public_key=r["signature_public_key"],
                    )
                    if r.get("signature")
                    and r.get("signature_key_id")
                    and r.get("signature_algorithm")
                    and r.get("signature_public_key")
                    else None
                ),
                violations=tuple(
                    Violation(**item) for item in json.loads(r.get("violations", "[]") or "[]")
                ),
            )
            for r in rows
        ]
