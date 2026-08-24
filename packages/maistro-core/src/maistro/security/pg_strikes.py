"""Postgres-backed strike tracker — survives restarts, works across workers/pods.

Satisfies `maistro.protocols.StrikeTracker`, the same protocol
`InMemoryStrikeTracker` does, so `Gate` cannot tell them apart (#134). It did
not before: both methods returned `dict`, while `Gate` does attribute access on
the result, so wiring this tracker raised `AttributeError` on the **first
security violation**. The docstring claimed it "replaces InMemoryStrikeTracker"
and the type system was not asked to check that, because both `Gate.__init__`
and `Container.strike_tracker` were typed against the concrete in-memory class.

The two implementations are now held to one conformance suite rather than one
docstring — see `tests/security/test_strike_tracker_conformance.py`.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from maistro.security.strikes import LOCKOUT_DURATION, StrikeRecord, ViolationRecord

logger = logging.getLogger("maistro.strikes")

# LOCKOUT_DURATION comes from `strikes.py` rather than being redeclared here.
# Two copies of a lockout window is two windows, and the one that matters is
# whichever module the reader happens to open.

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
    ) -> StrikeRecord:
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

            # Re-read rather than assembling a summary from what this function
            # happened to write. The escalation above is three separate UPDATEs
            # and returning `{"strike_count": n, "escalated": True}` described
            # the *change* while `Gate` reports the *state* — so a locked
            # account was announced to the caller as merely struck. Inside the
            # transaction, so the row read is the row written.
            record = await self._read(conn, user_id)
            if record is None:  # pragma: no cover - the upsert above guarantees a row
                msg = f"security_strikes row for {user_id!r} vanished mid-transaction"
                raise RuntimeError(msg)
            return record

    @staticmethod
    async def _read(conn: Any, user_id: str) -> StrikeRecord | None:
        """One row plus its violations, as the shared `StrikeRecord`."""
        row = await conn.fetchrow("SELECT * FROM security_strikes WHERE user_id=$1", user_id)
        if row is None:
            return None
        violations = await conn.fetch(
            "SELECT timestamp, flags, boundary, detail FROM security_violations "
            "WHERE user_id=$1 ORDER BY timestamp, id",
            user_id,
        )
        return StrikeRecord(
            user_id=row["user_id"],
            strike_count=row["strike_count"],
            scrutiny_level=row["scrutiny_level"],
            locked_until=row["locked_until"],
            disabled=row["disabled"],
            violations=[
                ViolationRecord(
                    timestamp=v["timestamp"],
                    flags=tuple(v["flags"] or ()),
                    boundary=v["boundary"],
                    detail=v["detail"] or "",
                )
                for v in violations
            ],
            last_violation_at=row["last_violation_at"],
            last_appeal=row["last_appeal"] or "",
            last_appeal_at=row["last_appeal_at"],
        )

    async def get(self, user_id: str) -> StrikeRecord | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await self._read(conn, user_id)

    async def is_locked(self, user_id: str) -> bool:
        record = await self.get(user_id)
        # `StrikeRecord.is_locked` rather than a second copy of the rule. The
        # dict form recomputed it here, which is how two implementations end up
        # disagreeing about whether an account is locked.
        return record.is_locked if record else False


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
