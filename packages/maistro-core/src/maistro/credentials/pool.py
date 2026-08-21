from __future__ import annotations

import random
import time

from maistro.credentials.types import (
    CredentialRecord,
    PoolExhaustedError,
    PoolStats,
    SelectionStrategy,
)


def fill_first(available: list[CredentialRecord]) -> CredentialRecord:
    return available[0]


def round_robin(available: list[CredentialRecord], index: int) -> tuple[CredentialRecord, int]:
    idx = index % len(available)
    return available[idx], idx + 1


def random_select(available: list[CredentialRecord]) -> CredentialRecord:
    # Non-crypto: this picks a credential record by index from a pool of
    # candidates a user has already authorized. The choice doesn't affect
    # secrecy — every record in `available` is equally authorized.
    return random.choice(available)  # nosec B311 — pool-selection, not crypto


def least_used(available: list[CredentialRecord]) -> CredentialRecord:
    return min(available, key=lambda e: e.use_count)


class CredentialPool:
    def __init__(
        self,
        provider: str,
        entries: list[CredentialRecord] | None = None,
        strategy: SelectionStrategy = SelectionStrategy.ROUND_ROBIN,
    ) -> None:
        self._provider = provider
        self._entries = sorted(entries or [], key=lambda e: e.priority)
        self._strategy = strategy
        self._rr_index = 0

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def strategy(self) -> SelectionStrategy:
        return self._strategy

    @property
    def size(self) -> int:
        return len(self._entries)

    def add(self, record: CredentialRecord) -> None:
        self._entries.append(record)
        self._entries.sort(key=lambda e: e.priority)

    def remove(self, key_id: str) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.key_id != key_id]
        return len(self._entries) < before

    def _available(self) -> list[CredentialRecord]:
        return [e for e in self._entries if e.is_available]

    def available_count(self) -> int:
        return len(self._available())

    def select(self) -> CredentialRecord:
        available = self._available()
        if not available:
            soonest = None
            for e in self._entries:
                if (
                    e.cooldown_until is not None
                    and not e.blocked
                    and (soonest is None or e.cooldown_until < soonest)
                ):
                    soonest = e.cooldown_until
            blocked = sum(1 for e in self._entries if e.blocked)
            cooling = sum(
                1
                for e in self._entries
                if not e.blocked and e.cooldown_until is not None and not e.is_available
            )
            raise PoolExhaustedError(
                message=f"All {len(self._entries)} credentials exhausted for {self._provider}",
                provider=self._provider,
                total_keys=len(self._entries),
                blocked_keys=blocked,
                cooling_down_keys=cooling,
                soonest_available_at=soonest,
            )

        if self._strategy == SelectionStrategy.FILL_FIRST:
            return fill_first(available)
        elif self._strategy == SelectionStrategy.ROUND_ROBIN:
            entry, self._rr_index = round_robin(available, self._rr_index)
            return entry
        elif self._strategy == SelectionStrategy.RANDOM:
            return random_select(available)
        elif self._strategy == SelectionStrategy.LEAST_USED:
            return least_used(available)
        raise ValueError(f"Unknown strategy: {self._strategy}")

    def record_success(self, key_id: str) -> None:
        entry = self._find(key_id)
        if entry:
            entry.last_status = 200
            entry.last_error_code = None
            entry.use_count += 1
            entry.last_used_at = time.monotonic()

    def record_failure(
        self,
        key_id: str,
        status_code: int = 0,
        error_code: str = "",
        cooldown_seconds: float = 0.0,
        block: bool = False,
    ) -> None:
        entry = self._find(key_id)
        if entry:
            entry.last_status = status_code
            entry.last_error_code = error_code
            entry.error_count += 1
            if block:
                entry.blocked = True
            elif cooldown_seconds > 0:
                entry.cooldown_until = time.monotonic() + cooldown_seconds

    def clear_cooldown(self, key_id: str) -> None:
        entry = self._find(key_id)
        if entry:
            entry.cooldown_until = None
            entry.blocked = False
            entry.last_status = None
            entry.last_error_code = None

    def clear_all_cooldowns(self) -> None:
        for entry in self._entries:
            entry.cooldown_until = None
            entry.blocked = False
            entry.last_status = None
            entry.last_error_code = None

    def get_stats(self) -> PoolStats:
        available = self._available()
        blocked = [e for e in self._entries if e.blocked]
        cooling = [
            e
            for e in self._entries
            if not e.blocked and e.cooldown_until is not None and not e.is_available
        ]
        return PoolStats(
            provider=self._provider,
            strategy=self._strategy,
            total_keys=len(self._entries),
            available_keys=len(available),
            blocked_keys=len(blocked),
            cooling_down_keys=len(cooling),
            total_use_count=sum(e.use_count for e in self._entries),
            total_error_count=sum(e.error_count for e in self._entries),
            per_key=[
                {
                    "key_id": e.key_id,
                    # `is_available`, matching the CredentialRecord property it
                    # copies — every other key in this dict mirrors its source
                    # attribute exactly, and ADR-063 declares per_key as
                    # list[CredentialRecord]. The bare `available` was a slip
                    # introduced while flattening the record into a dict.
                    "is_available": e.is_available,
                    "blocked": e.blocked,
                    "use_count": e.use_count,
                    "error_count": e.error_count,
                    "last_status": e.last_status,
                    "cooldown_remaining": max(0.0, (e.cooldown_until or 0) - time.monotonic()),
                }
                for e in self._entries
            ],
        )

    def _find(self, key_id: str) -> CredentialRecord | None:
        for entry in self._entries:
            if entry.key_id == key_id:
                return entry
        return None
