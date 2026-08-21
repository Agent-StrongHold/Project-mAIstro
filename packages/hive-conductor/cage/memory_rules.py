"""Memory rules — enforce append-only semantics for durable memory tiers.

Tiers:
  - ephemeral: read/write/delete freely (session-scoped)
  - durable: append-only — can add entries, CANNOT modify or delete existing
  - permanent: read-only — frozen at creation, never changes

Turing can never:
  - Delete a durable memory entry
  - Modify a durable memory entry's content
  - Modify or delete any permanent memory entry
  - Backdate timestamps
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MemoryTier(StrEnum):
    EPHEMERAL = "ephemeral"
    DURABLE = "durable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class MemoryViolation:
    action: str
    tier: MemoryTier
    key: str
    reason: str


class MemoryRules:
    """Enforces memory tier constraints. Returns violations instead of raising."""

    def check_write(
        self, tier: MemoryTier, key: str, existing: Any | None
    ) -> MemoryViolation | None:
        if tier == MemoryTier.PERMANENT and existing is not None:
            return MemoryViolation(
                "write", tier, key, "permanent memory is read-only after creation"
            )
        if tier == MemoryTier.DURABLE and existing is not None:
            return MemoryViolation(
                "write", tier, key, "durable memory is append-only; cannot overwrite"
            )
        return None

    def check_delete(self, tier: MemoryTier, key: str) -> MemoryViolation | None:
        if tier == MemoryTier.PERMANENT:
            return MemoryViolation("delete", tier, key, "permanent memory cannot be deleted")
        if tier == MemoryTier.DURABLE:
            return MemoryViolation("delete", tier, key, "durable memory cannot be deleted")
        return None

    def check_timestamp(
        self, proposed: datetime, now: datetime | None = None
    ) -> MemoryViolation | None:
        now = now or datetime.now(UTC)
        if proposed < now:
            return MemoryViolation(
                "timestamp", MemoryTier.DURABLE, "", "cannot backdate timestamps"
            )
        return None
