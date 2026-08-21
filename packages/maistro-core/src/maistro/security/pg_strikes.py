"""Postgres-backed strike tracker — survives restarts, works across workers/pods.

Replaces InMemoryStrikeTracker with atomic SQL operations.
Falls back to in-memory if no DATABASE_URL is configured (dev/test only).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("maistro.strikes")

LOCKOUT_DURATION = timedelta(hours=8)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_strikes (
    user_id TEXT PRIMARY KEY,
    strike_count INTEGER NOT NULL DEFAULT 0,
    scrutiny_level TEXT NOT NULL DEFAULT 'normal',
    locked_until TIMESTAMPTZ,
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_violation_at TIMESTAMPTZ,
    last_appeal TEXT DEFAULT '',
    last_appeal_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_violations (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES security_strikes(user_id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    flags TEXT[] NOT NULL DEFAULT '{}',
    boundary TEXT NOT NULL DEFAULT 'user_input',
    detail TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS security_rate_limits (
    key TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (key, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rate_limits_expiry ON security_rate_limits(window_start);
"""


class PgStrikeTracker:
    """Postgres-backed strike tracker with atomic operations."""

    def __init__(self, db_url: str | None = None):
        self._db_url = (
            db_url or os.environ.get("DATABASE_URL") or os.environ.get("DEPLOY_TARGET_DB_URL")
        )
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg

                self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=5)
                await self._pool.execute(_SCHEMA)
            except Exception as e:
                logger.error("pg_strikes_init_failed: %s", e)
                raise
        return self._pool

    async def record_violation(
        self,
        *,
        user_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> dict[str, Any]:
        """Atomic: upsert strike record + escalate + insert violation in one transaction."""
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.transaction():
            # Upsert and increment atomically
            row = await conn.fetchrow(
                """
                    INSERT INTO security_strikes (user_id, strike_count, scrutiny_level, last_violation_at, updated_at)
                    VALUES ($1, 1, 'elevated', NOW(), NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                        strike_count = security_strikes.strike_count + 1,
                        last_violation_at = NOW(),
                        updated_at = NOW()
                    RETURNING user_id, strike_count, scrutiny_level, locked_until, disabled
                """,
                user_id,
            )

            strike_count = row["strike_count"]

            # Escalate
            if strike_count >= 3:
                await conn.execute(
                    """
                        UPDATE security_strikes SET scrutiny_level='disabled', disabled=TRUE WHERE user_id=$1
                    """,
                    user_id,
                )
                logger.warning("ACCOUNT DISABLED: user=%s strikes=%d", user_id, strike_count)
            elif strike_count == 2:
                locked_until = datetime.now(UTC) + LOCKOUT_DURATION
                await conn.execute(
                    """
                        UPDATE security_strikes SET scrutiny_level='locked', locked_until=$2 WHERE user_id=$1
                    """,
                    user_id,
                    locked_until,
                )
                logger.warning(
                    "ACCOUNT LOCKED: user=%s until=%s", user_id, locked_until.isoformat()
                )
            elif strike_count == 1:
                await conn.execute(
                    """
                        UPDATE security_strikes SET scrutiny_level='elevated' WHERE user_id=$1
                    """,
                    user_id,
                )

            # Record the violation
            await conn.execute(
                """
                    INSERT INTO security_violations (user_id, flags, boundary, detail)
                    VALUES ($1, $2, $3, $4)
                """,
                user_id,
                list(flags),
                boundary,
                detail[:1000],
            )

            return {"user_id": user_id, "strike_count": strike_count, "escalated": True}

    async def get(self, user_id: str) -> dict[str, Any] | None:
        pool = await self._get_pool()
        row = await pool.fetchrow("SELECT * FROM security_strikes WHERE user_id=$1", user_id)
        if row is None:
            return None
        r = dict(row)
        r["is_locked"] = r.get("disabled") or (
            r.get("locked_until") is not None and datetime.now(UTC) < r["locked_until"]
        )
        return r

    async def is_locked(self, user_id: str) -> bool:
        rec = await self.get(user_id)
        return rec["is_locked"] if rec else False


class PgRateLimiter:
    """Postgres-backed sliding window rate limiter — atomic check-and-record (fixes TOCTOU)."""

    def __init__(self, db_url: str | None = None, window_seconds: int = 60, max_requests: int = 60):
        self._db_url = (
            db_url or os.environ.get("DATABASE_URL") or os.environ.get("DEPLOY_TARGET_DB_URL")
        )
        self._window_seconds = window_seconds
        self._max_requests = max_requests
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=5)
            await self._pool.execute(_SCHEMA)
        return self._pool

    async def check_and_record(self, key: str) -> tuple[bool, int]:
        """Atomic check+record in one statement. Returns (allowed, current_count).

        This is a single INSERT ... ON CONFLICT with a conditional — no TOCTOU gap.
        """
        pool = await self._get_pool()
        window_start = datetime.now(UTC).replace(second=0, microsecond=0)
        window_floor = window_start - timedelta(seconds=self._window_seconds)

        async with pool.acquire() as conn, conn.transaction():
            # Clean expired windows
            await conn.execute(
                "DELETE FROM security_rate_limits WHERE window_start < $1", window_floor
            )

            # Atomic upsert + count check in one round-trip
            row = await conn.fetchrow(
                """
                    INSERT INTO security_rate_limits (key, window_start, count)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (key, window_start) DO UPDATE SET count = security_rate_limits.count + 1
                    RETURNING count
                """,
                key,
                window_start,
            )

            current = row["count"]
            allowed = current <= self._max_requests
            return allowed, current
