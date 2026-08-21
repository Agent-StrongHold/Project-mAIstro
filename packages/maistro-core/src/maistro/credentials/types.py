from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SelectionStrategy(StrEnum):
    FILL_FIRST = "fill_first"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"


@dataclass
class CredentialRecord:
    key_id: str
    provider: str
    api_key: str
    priority: int = 0

    last_status: int | None = None
    last_error_code: str | None = None
    cooldown_until: float | None = None
    blocked: bool = False

    use_count: int = 0
    error_count: int = 0
    last_used_at: float | None = None

    @property
    def is_available(self) -> bool:
        if self.blocked:
            return False
        if self.cooldown_until is None:
            return True
        return time.monotonic() >= self.cooldown_until


@dataclass
class PoolExhaustedError(Exception):
    message: str
    provider: str = ""
    total_keys: int = 0
    blocked_keys: int = 0
    cooling_down_keys: int = 0
    soonest_available_at: float | None = None

    @property
    def wait_seconds(self) -> float:
        if self.soonest_available_at is None:
            return 0.0
        return max(0.0, self.soonest_available_at - time.monotonic())


@dataclass
class PoolStats:
    provider: str
    strategy: SelectionStrategy
    total_keys: int = 0
    available_keys: int = 0
    blocked_keys: int = 0
    cooling_down_keys: int = 0
    total_use_count: int = 0
    total_error_count: int = 0
    per_key: list[dict[str, Any]] = field(default_factory=list)
