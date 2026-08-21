"""Strike tracker: per-user violation escalation with lockout and disable.

Escalation ladder:
  Strike 1 -- Warning + elevated scrutiny (L3 classifier enabled for user)
  Strike 2 -- 8-hour lockout (team_admin+ to unlock)
  Strike 3 -- Account disabled (admin+ to re-enable)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("maistro.strikes")

LOCKOUT_DURATION = timedelta(hours=8)

NORMAL = "normal"
ELEVATED = "elevated"
LOCKED = "locked"
DISABLED = "disabled"


@dataclass
class ViolationRecord:
    timestamp: datetime
    flags: tuple[str, ...]
    boundary: str
    detail: str = ""


@dataclass
class StrikeRecord:
    user_id: str
    strike_count: int = 0
    scrutiny_level: str = NORMAL
    locked_until: datetime | None = None
    disabled: bool = False
    violations: list[ViolationRecord] = field(default_factory=list)
    last_violation_at: datetime | None = None
    last_appeal: str = ""
    last_appeal_at: datetime | None = None

    @property
    def is_locked(self) -> bool:
        if self.disabled:
            return True
        if self.locked_until is not None:
            return datetime.now(UTC) < self.locked_until
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "strike_count": self.strike_count,
            "scrutiny_level": self.scrutiny_level,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "disabled": self.disabled,
            "is_locked": self.is_locked,
            "violation_count": len(self.violations),
            "last_violation_at": (
                self.last_violation_at.isoformat() if self.last_violation_at else None
            ),
            "last_appeal": self.last_appeal,
        }


class InMemoryStrikeTracker:
    """In-memory strike tracker."""

    def __init__(self) -> None:
        self._records: dict[str, StrikeRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> StrikeRecord | None:
        return self._records.get(user_id)

    async def record_violation(
        self,
        *,
        user_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> StrikeRecord:
        async with self._lock:
            now = datetime.now(UTC)

            record = self._records.get(user_id)
            if record is None:
                record = StrikeRecord(user_id=user_id)
                self._records[user_id] = record

            violation = ViolationRecord(
                timestamp=now,
                flags=flags,
                boundary=boundary,
                detail=detail,
            )
            record.violations.append(violation)
            record.last_violation_at = now

            record.strike_count += 1

            if record.strike_count >= 3:
                record.scrutiny_level = DISABLED
                record.disabled = True
                logger.warning(
                    "ACCOUNT DISABLED: user=%s strikes=%d",
                    user_id,
                    record.strike_count,
                )
            elif record.strike_count == 2:
                record.scrutiny_level = LOCKED
                record.locked_until = now + LOCKOUT_DURATION
                logger.warning(
                    "ACCOUNT LOCKED: user=%s until=%s",
                    user_id,
                    record.locked_until.isoformat(),
                )
            elif record.strike_count == 1:
                record.scrutiny_level = ELEVATED
                logger.warning(
                    "STRIKE 1: user=%s -- elevated scrutiny enabled",
                    user_id,
                )

            return record

    async def submit_appeal(
        self,
        user_id: str,
        appeal_text: str,
    ) -> bool:
        record = self._records.get(user_id)
        if record is None or record.strike_count == 0:
            return False
        record.last_appeal = appeal_text
        record.last_appeal_at = datetime.now(UTC)
        logger.info("Appeal submitted: user=%s text=%s", user_id, appeal_text[:100])
        return True

    async def remove_strikes(
        self,
        user_id: str,
        count: int | None = None,
    ) -> StrikeRecord | None:
        record = self._records.get(user_id)
        if record is None:
            return None

        if count is None:
            record.strike_count = 0
        else:
            record.strike_count = max(0, record.strike_count - count)

        self._recalculate_level(record)

        logger.info(
            "Strikes removed: user=%s new_count=%d level=%s",
            user_id,
            record.strike_count,
            record.scrutiny_level,
        )
        return record

    async def unlock(self, user_id: str) -> StrikeRecord | None:
        record = self._records.get(user_id)
        if record is None:
            return None

        record.locked_until = None
        if not record.disabled:
            record.scrutiny_level = ELEVATED if record.strike_count >= 1 else NORMAL

        logger.info("Account unlocked: user=%s", user_id)
        return record

    async def enable(self, user_id: str) -> StrikeRecord | None:
        record = self._records.get(user_id)
        if record is None:
            return None

        record.disabled = False
        record.locked_until = None
        record.scrutiny_level = ELEVATED if record.strike_count >= 1 else NORMAL

        logger.info("Account re-enabled: user=%s", user_id)
        return record

    @staticmethod
    def _recalculate_level(record: StrikeRecord) -> None:
        if record.strike_count >= 3:
            record.scrutiny_level = DISABLED
            record.disabled = True
        elif record.strike_count == 2:
            record.scrutiny_level = LOCKED
        elif record.strike_count >= 1:
            record.scrutiny_level = ELEVATED
            record.disabled = False
            record.locked_until = None
        else:
            record.scrutiny_level = NORMAL
            record.disabled = False
            record.locked_until = None
