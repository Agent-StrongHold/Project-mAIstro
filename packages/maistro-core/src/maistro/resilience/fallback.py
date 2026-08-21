from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from maistro.resilience.classifier import ClassifiedError, ErrorCategory, classify_error


class FailoverReason(StrEnum):
    RATE_LIMIT = "rate_limit"
    OVERLOAD = "overload"
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    UNKNOWN = "unknown"


def _classify_to_reason(classified: ClassifiedError) -> FailoverReason:
    mapping: dict[ErrorCategory, FailoverReason] = {
        ErrorCategory.RATE_LIMIT: FailoverReason.RATE_LIMIT,
        ErrorCategory.PROVIDER: FailoverReason.OVERLOAD,
        ErrorCategory.NETWORK: FailoverReason.CONNECTION,
        ErrorCategory.TIMEOUT: FailoverReason.TIMEOUT,
        ErrorCategory.CONTEXT_OVERFLOW: FailoverReason.CONTEXT_OVERFLOW,
    }
    return mapping.get(classified.category, FailoverReason.UNKNOWN)


@dataclass
class ProviderEndpoint:
    name: str
    model: str
    api_key: str = ""
    base_url: str = ""
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FallbackState:
    current_index: int = 0
    failover_count: int = 0
    last_failover_at: float | None = None
    last_failover_reason: FailoverReason | None = None
    primary_restore_at: float | None = None
    consecutive_successes: int = 0

    @property
    def is_on_primary(self) -> bool:
        return self.current_index == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_index": self.current_index,
            "failover_count": self.failover_count,
            "last_failover_reason": self.last_failover_reason.value
            if self.last_failover_reason
            else None,
            "is_on_primary": self.is_on_primary,
            "consecutive_successes": self.consecutive_successes,
        }


@dataclass
class FallbackChainConfig:
    restore_after_successes: int = 3
    restore_cooldown_seconds: float = 30.0
    max_failovers: int = 10
    retry_primary_on_context_overflow: bool = False


class FallbackChain:
    def __init__(
        self,
        endpoints: list[ProviderEndpoint],
        config: FallbackChainConfig | None = None,
    ) -> None:
        if not endpoints:
            raise ValueError("FallbackChain requires at least one endpoint")
        self._endpoints = sorted(endpoints, key=lambda e: e.priority)
        self._config = config or FallbackChainConfig()
        self._state = FallbackState()

    @property
    def state(self) -> FallbackState:
        return self._state

    @property
    def current(self) -> ProviderEndpoint:
        return self._endpoints[self._state.current_index]

    @property
    def primary(self) -> ProviderEndpoint:
        return self._endpoints[0]

    @property
    def endpoints(self) -> list[ProviderEndpoint]:
        return list(self._endpoints)

    def record_success(self) -> None:
        self._state.consecutive_successes += 1
        if (
            not self._state.is_on_primary
            and self._state.consecutive_successes >= self._config.restore_after_successes
        ):
            self._try_restore_primary()

    def record_failure(self, exc: Exception) -> bool:
        classified = classify_error(exc)
        if not classified.retryable and classified.category != ErrorCategory.CONTEXT_OVERFLOW:
            return False

        reason = _classify_to_reason(classified)
        if self._state.current_index >= len(self._endpoints) - 1:
            return False

        if self._state.failover_count >= self._config.max_failovers:
            return False

        if (
            reason == FailoverReason.CONTEXT_OVERFLOW
            and self._config.retry_primary_on_context_overflow
        ):
            return False

        self._state.current_index += 1
        self._state.failover_count += 1
        self._state.last_failover_at = time.monotonic()
        self._state.last_failover_reason = reason
        self._state.consecutive_successes = 0
        return True

    def _try_restore_primary(self) -> bool:
        if self._state.is_on_primary:
            return False
        now = time.monotonic()
        if self._state.last_failover_at is not None:
            elapsed = now - self._state.last_failover_at
            if elapsed < self._config.restore_cooldown_seconds:
                return False
        prev = self._state.current_index
        self._state.current_index = 0
        self._state.primary_restore_at = now
        self._state.consecutive_successes = 0
        return prev != 0

    def reset(self) -> None:
        self._state = FallbackState()

    def next_endpoint_after_failure(self, exc: Exception) -> ProviderEndpoint | None:
        if self.record_failure(exc):
            return self.current
        return None
