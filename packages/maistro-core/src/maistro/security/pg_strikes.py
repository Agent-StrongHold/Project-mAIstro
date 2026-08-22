"""Postgres-backed strike tracker — survives restarts, works across workers (#134).

Lockout state that resets on restart is a lockout an attacker clears by waiting
for a deploy, and an in-memory ladder is only as shared as one process. This is
the durable one.

It used to describe itself as replacing `InMemoryStrikeTracker` and did not:
`get()` returned a dict where `Gate` does attribute access on a `StrikeRecord`,
and `record_violation()` returned three keys where `Gate` reads six, so wiring
it would have raised AttributeError on the first security violation — the worst
possible place. It now returns `StrikeRecord` throughout and satisfies
`maistro.protocols.StrikeTracker`, which is what makes the substitution a
checked fact rather than a docstring.

Two other things changed with it. The pool is injected rather than built from an
ambient `DATABASE_URL`, like every other store in `maistro.persistence` — a
component that reaches for the environment is a component that cannot be pointed
somewhere else. And the tables come from `alembic/versions/005` instead of a
`CREATE TABLE` executed on first use: provisioning belongs in one place, or the
schema a deployment has depends on which code path ran first.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from maistro.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    NORMAL,
    StrikeRecord,
    ViolationRecord,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

logger = logging.getLogger("maistro.strikes")

LOCKOUT_DURATION = timedelta(hours=8)

#: How many recent violations `get()` loads with a record. The full history can
#: be long and `Gate` never reads it — it needs the counters and the lock state.
#: An admin surface that wants the whole history should query for it.
RECENT_VIOLATIONS = 20


def _record_from_row(row: Any, violations: list[ViolationRecord] | None = None) -> StrikeRecord:
    """Build the canonical record from a `security_strikes` row.

    The dataclass computes `is_locked` from `disabled` and `locked_until`, so it
    is deliberately not read from the row: two sources for one answer is how the
    in-memory and durable trackers would drift apart on the question that
    matters most.
    """
    return StrikeRecord(
        user_id=row["user_id"],
        strike_count=int(row["strike_count"]),
        scrutiny_level=str(row["scrutiny_level"]),
        locked_until=row["locked_until"],
        disabled=bool(row["disabled"]),
        violations=violations or [],
        last_violation_at=row["last_violation_at"],
        last_appeal=str(row["last_appeal"] or ""),
        last_appeal_at=row["last_appeal_at"],
    )


def _level_for(strike_count: int) -> tuple[str, bool]:
    """The scrutiny level and disabled flag a strike count implies.

    Shared by escalation and by administrative removal so the ladder is defined
    once. `InMemoryStrikeTracker._recalculate_level` is the same table.
    """
    if strike_count >= 3:
        return DISABLED, True
    if strike_count == 2:
        return LOCKED, False
    if strike_count >= 1:
        return ELEVATED, False
    return NORMAL, False


class PgStrikeTracker:
    """Postgres-backed strike tracker with atomic escalation."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, user_id: str) -> StrikeRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM security_strikes WHERE user_id = $1", user_id)
            if row is None:
                return None
            violations = await conn.fetch(
                """SELECT timestamp, flags, boundary, detail
                   FROM security_violations WHERE user_id = $1
                   ORDER BY timestamp DESC LIMIT $2""",
                user_id,
                RECENT_VIOLATIONS,
            )
        return _record_from_row(
            row,
            [
                ViolationRecord(
                    timestamp=v["timestamp"],
                    flags=tuple(v["flags"] or ()),
                    boundary=str(v["boundary"] or ""),
                    detail=str(v["detail"] or ""),
                )
                for v in reversed(violations)
            ],
        )

    async def record_violation(
        self,
        *,
        user_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> StrikeRecord:
        """Increment, escalate and log the violation in one transaction.

        One statement does the increment *and* the escalation, rather than
        incrementing then reading then updating: two concurrent violations by
        the same user would otherwise both read the pre-escalation count and the
        second would write a level the first had already passed.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO security_strikes
                       (user_id, strike_count, scrutiny_level, last_violation_at, updated_at)
                   VALUES ($1, 1, $2, NOW(), NOW())
                   ON CONFLICT (user_id) DO UPDATE SET
                       strike_count = security_strikes.strike_count + 1,
                       scrutiny_level = CASE
                           WHEN security_strikes.strike_count + 1 >= 3 THEN $3
                           WHEN security_strikes.strike_count + 1 = 2 THEN $4
                           ELSE $2
                       END,
                       disabled = (security_strikes.strike_count + 1) >= 3,
                       locked_until = CASE
                           WHEN security_strikes.strike_count + 1 = 2 THEN $5
                           ELSE security_strikes.locked_until
                       END,
                       last_violation_at = NOW(),
                       updated_at = NOW()
                   RETURNING *""",
                user_id,
                ELEVATED,
                DISABLED,
                LOCKED,
                datetime.now(UTC) + LOCKOUT_DURATION,
            )
            await conn.execute(
                """INSERT INTO security_violations (user_id, flags, boundary, detail)
                   VALUES ($1, $2, $3, $4)""",
                user_id,
                list(flags),
                boundary,
                detail[:1000],
            )
        record = _record_from_row(row)
        _log_escalation(record)
        return record

    async def submit_appeal(self, user_id: str, appeal_text: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE security_strikes
                   SET last_appeal = $2, last_appeal_at = NOW(), updated_at = NOW()
                   WHERE user_id = $1 AND strike_count > 0
                   RETURNING user_id""",
                user_id,
                appeal_text,
            )
        if row is None:
            return False
        logger.info("Appeal submitted: user=%s text=%s", user_id, appeal_text[:100])
        return True

    async def remove_strikes(self, user_id: str, count: int | None = None) -> StrikeRecord | None:
        """Forgive strikes and recompute the ladder from what remains."""
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT strike_count FROM security_strikes WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if row is None:
                return None
            remaining = 0 if count is None else max(0, int(row["strike_count"]) - count)
            level, disabled = _level_for(remaining)
            updated = await conn.fetchrow(
                """UPDATE security_strikes
                   SET strike_count = $2,
                       scrutiny_level = $3,
                       disabled = $4,
                       locked_until = CASE WHEN $5 THEN locked_until ELSE NULL END,
                       updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                remaining,
                level,
                disabled,
                remaining >= 2,
            )
        logger.info("Strikes removed: user=%s new_count=%d level=%s", user_id, remaining, level)
        return _record_from_row(updated)

    async def unlock(self, user_id: str) -> StrikeRecord | None:
        """Lift a timed lockout, leaving the strikes that caused it in place."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE security_strikes
                   SET locked_until = NULL,
                       scrutiny_level = CASE
                           WHEN disabled THEN scrutiny_level
                           WHEN strike_count >= 1 THEN $2
                           ELSE $3
                       END,
                       updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                ELEVATED,
                NORMAL,
            )
        if row is None:
            return None
        logger.info("Account unlocked: user=%s", user_id)
        return _record_from_row(row)

    async def enable(self, user_id: str) -> StrikeRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE security_strikes
                   SET disabled = FALSE,
                       locked_until = NULL,
                       scrutiny_level = CASE WHEN strike_count >= 1 THEN $2 ELSE $3 END,
                       updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                ELEVATED,
                NORMAL,
            )
        if row is None:
            return None
        logger.info("Account re-enabled: user=%s", user_id)
        return _record_from_row(row)

    async def is_locked(self, user_id: str) -> bool:
        record = await self.get(user_id)
        return record.is_locked if record else False


def _log_escalation(record: StrikeRecord) -> None:
    """Say what the ladder just did, at the level the event deserves."""
    if record.disabled:
        logger.warning("ACCOUNT DISABLED: user=%s strikes=%d", record.user_id, record.strike_count)
    elif record.locked_until is not None and record.strike_count == 2:
        logger.warning(
            "ACCOUNT LOCKED: user=%s until=%s",
            record.user_id,
            record.locked_until.isoformat(),
        )
    elif record.strike_count == 1:
        logger.warning("STRIKE 1: user=%s -- elevated scrutiny enabled", record.user_id)


class PgRateLimiter:
    """Postgres-backed sliding window rate limiter — atomic check-and-record (fixes TOCTOU)."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        window_seconds: int = 60,
        max_requests: int = 60,
    ) -> None:
        """Bind to an application-owned pool.

        Injected for the same reason `PgStrikeTracker`'s is: a component that
        reaches into the environment for a connection string is a component
        that cannot be pointed anywhere else, and it opens a second pool to a
        database the process is already connected to.
        """
        self._pool = pool
        self._window_seconds = window_seconds
        self._max_requests = max_requests

    async def check_and_record(self, key: str) -> tuple[bool, int]:
        """Atomic check+record in one statement. Returns (allowed, current_count).

        This is a single INSERT ... ON CONFLICT with a conditional — no TOCTOU gap.
        """
        window_start = datetime.now(UTC).replace(second=0, microsecond=0)
        window_floor = window_start - timedelta(seconds=self._window_seconds)

        async with self._pool.acquire() as conn, conn.transaction():
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
