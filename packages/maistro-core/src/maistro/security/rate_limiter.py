"""In-memory rate limiter: sliding window counter per key.

Uses a deque of timestamps per key. Each check prunes expired entries,
then counts remaining. O(1) amortized per check.

Enforces both RPM (requests per minute) and burst limits.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from maistro.security._types import RateLimitConfig

_KEY_EVICTION_AGE_S = 300
_EVICTION_INTERVAL = 1000


class InMemoryRateLimiter:
    """Sliding window rate limiter."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        if config is None:
            config = RateLimitConfig()
        cfg = config
        self._rpm = cfg.requests_per_minute
        self._burst = cfg.burst_limit
        self._enabled = cfg.enabled
        self._window = 60.0
        self._burst_window = 1.0
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._check_count = 0
        self._last_eviction = time.monotonic()

    async def check(self, key: str) -> tuple[bool, dict[str, str]]:
        if not self._enabled:
            return True, {}

        now = time.monotonic()
        window = self._windows[key]

        cutoff = now - self._window
        while window and window[0] < cutoff:
            window.popleft()

        remaining = max(self._rpm - len(window), 0)
        reset_seconds = int(self._window - (now - window[0])) if window else int(self._window)

        headers = {
            "X-RateLimit-Limit": str(self._rpm),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_seconds),
        }

        if len(window) >= self._rpm:
            return False, headers

        if self._burst > 0:
            burst_cutoff = now - self._burst_window
            recent = sum(1 for ts in window if ts >= burst_cutoff)
            if recent >= self._burst:
                headers["X-RateLimit-Remaining"] = "0"
                return False, headers

        self._check_count += 1
        if self._check_count >= _EVICTION_INTERVAL:
            self._evict_stale_keys(now)

        return True, headers

    async def record(self, key: str) -> None:
        if not self._enabled:
            return
        self._windows[key].append(time.monotonic())

    def _evict_stale_keys(self, now: float) -> None:
        self._check_count = 0
        self._last_eviction = now
        eviction_cutoff = now - _KEY_EVICTION_AGE_S
        stale_keys = [k for k, v in self._windows.items() if not v or v[-1] < eviction_cutoff]
        for k in stale_keys:
            del self._windows[k]
