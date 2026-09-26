"""SQLite-backed quota tracker (homelab/single-instance deployments)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import uuid4

from maistro.persistence.pg_quota import cycle_key
from maistro.sqlite_schema import serialized_schema_upgrade

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quota_usage (
    provider TEXT NOT NULL,
    cycle_key TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, cycle_key)
)
"""

_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS quota_usage_events (
    event_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    cycle_key TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL
)
"""


class SqliteQuotaTracker:
    """SQLite-backed quota tracker implementing the same protocol as PgQuotaTracker."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._record_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the quota_usage and quota_usage_events tables.

        `quota_usage_events` carries the durable event identities that make
        `record_usage` retries (and crash-ambiguous commits) harmless.
        """
        async with serialized_schema_upgrade(self._conn):
            await self._conn.execute(_SCHEMA)
            await self._conn.execute(_EVENT_SCHEMA)

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        event_id: str | None = None,
    ) -> dict[str, object]:
        """Record one event, making retries harmless by ``event_id``."""
        event_id = event_id or uuid4().hex
        ck = cycle_key(billing_cycle)
        total = input_tokens + output_tokens
        async with self._record_lock:
            cursor = await self._conn.execute(
                "INSERT OR IGNORE INTO quota_usage_events "
                "(event_id, provider, cycle_key, input_tokens, output_tokens) VALUES (?, ?, ?, ?, ?)",
                (event_id, provider, ck, input_tokens, output_tokens),
            )
            if cursor.rowcount == 0:
                existing = await self._conn.execute(
                    "SELECT provider, cycle_key, input_tokens, output_tokens "
                    "FROM quota_usage_events WHERE event_id = ?",
                    (event_id,),
                )
                stored = await existing.fetchone()
                if stored is None or stored != (provider, ck, input_tokens, output_tokens):
                    raise ValueError(f"event_id {event_id!r} was reused with different usage")
            else:
                await self._conn.execute(
                    """INSERT INTO quota_usage
                       (provider, cycle_key, input_tokens, output_tokens, total_tokens, request_count)
                       VALUES (?, ?, ?, ?, ?, 1)
                       ON CONFLICT (provider, cycle_key) DO UPDATE SET
                         input_tokens = input_tokens + excluded.input_tokens,
                         output_tokens = output_tokens + excluded.output_tokens,
                         total_tokens = total_tokens + excluded.total_tokens,
                         request_count = request_count + 1""",
                    (provider, ck, input_tokens, output_tokens, total),
                )
            await self._conn.commit()
            cursor = await self._conn.execute(
                "SELECT input_tokens, output_tokens, total_tokens, request_count "
                "FROM quota_usage WHERE provider = ? AND cycle_key = ?",
                (provider, ck),
            )
            row = await cursor.fetchone()
        return {
            "provider": provider,
            "cycle_key": ck,
            "input_tokens": row[0] if row else 0,
            "output_tokens": row[1] if row else 0,
            "total_tokens": row[2] if row else 0,
            "request_count": row[3] if row else 0,
        }

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        """Get usage as a percentage of free tier."""
        if free_tokens <= 0:
            return 0.0
        ck = cycle_key(billing_cycle)
        cursor = await self._conn.execute(
            "SELECT total_tokens FROM quota_usage WHERE provider = ? AND cycle_key = ?",
            (provider, ck),
        )
        row = await cursor.fetchone()
        total: int = row[0] if row else 0
        return total / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get all usage records."""
        cursor = await self._conn.execute(
            "SELECT provider, cycle_key, input_tokens, output_tokens, total_tokens, "
            "request_count FROM quota_usage ORDER BY provider, cycle_key",
        )
        rows = await cursor.fetchall()
        return [
            {
                "provider": r[0],
                "cycle_key": r[1],
                "input_tokens": r[2],
                "output_tokens": r[3],
                "total_tokens": r[4],
                "request_count": r[5],
            }
            for r in rows
        ]
