"""Coverage for maistro.security.rate_limiter.InMemoryRateLimiter (was 0%)."""

from __future__ import annotations

import time

import pytest

from maistro.security._types import RateLimitConfig
from maistro.security.rate_limiter import InMemoryRateLimiter


async def test_disabled_limiter_always_allows() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(enabled=False))
    for _ in range(100):
        allowed, headers = await limiter.check("user-a")
        assert allowed is True
        assert headers == {}


async def test_default_config_used_when_none_passed() -> None:
    limiter = InMemoryRateLimiter()
    allowed, headers = await limiter.check("user-a")
    assert allowed is True
    assert headers["X-RateLimit-Limit"] == "60"


async def test_allows_requests_under_rpm_limit() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=5, burst_limit=0))
    for _ in range(5):
        allowed, _ = await limiter.check("user-a")
        assert allowed is True
        await limiter.record("user-a")

    # 5 requests recorded against a limit of 5 -> window is full, remaining 0.
    allowed, headers = await limiter.check("user-a")
    assert allowed is False
    assert headers["X-RateLimit-Remaining"] == "0"


async def test_denies_request_once_rpm_exceeded() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=3, burst_limit=0))
    for _ in range(3):
        allowed, _ = await limiter.check("user-a")
        assert allowed is True
        await limiter.record("user-a")

    allowed, headers = await limiter.check("user-a")
    assert allowed is False
    assert headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in headers


async def test_burst_limit_denies_rapid_requests_within_burst_window() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=100, burst_limit=2))
    await limiter.record("user-a")
    await limiter.record("user-a")

    allowed, headers = await limiter.check("user-a")
    assert allowed is False
    assert headers["X-RateLimit-Remaining"] == "0"


async def test_burst_limit_zero_disables_burst_check() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=100, burst_limit=0))
    for _ in range(10):
        await limiter.record("user-a")
    allowed, _ = await limiter.check("user-a")
    assert allowed is True


async def test_keys_are_independent() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=1, burst_limit=0))
    await limiter.record("user-a")
    allowed_a, _ = await limiter.check("user-a")
    allowed_b, _ = await limiter.check("user-b")
    assert allowed_a is False
    assert allowed_b is True


async def test_record_is_noop_when_disabled() -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(enabled=False, requests_per_minute=1))
    await limiter.record("user-a")
    assert "user-a" not in limiter._windows


async def test_sliding_window_expires_old_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=1, burst_limit=0))
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base)
    await limiter.record("user-a")

    allowed, _ = await limiter.check("user-a")
    assert allowed is False

    monkeypatch.setattr(time, "monotonic", lambda: base + 61)
    allowed, _ = await limiter.check("user-a")
    assert allowed is True


async def test_eviction_runs_after_interval_and_drops_stale_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = InMemoryRateLimiter(RateLimitConfig(requests_per_minute=1000, burst_limit=0))
    base = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: base)
    await limiter.record("stale-key")

    # Move far enough that stale-key is older than the eviction age.
    later = base + 301
    monkeypatch.setattr(time, "monotonic", lambda: later)

    limiter._check_count = 999  # one more check triggers eviction
    await limiter.check("fresh-key")

    assert "stale-key" not in limiter._windows
