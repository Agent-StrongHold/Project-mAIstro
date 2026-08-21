"""Rate pacer: malformed headers must not abort calls, and an exhausted
budget must be waited out, not pinged every 65 seconds.

Both are Codex findings on #262, pinned here on their motivating inputs.
"""

from __future__ import annotations

import pytest

from maistro_rsi.rate_pacer import RatePacer, _parse_duration


class TestParseDurationMalformed:
    """`Retry-After: 47..s` is untrusted wire input; the contract is None,
    never ValueError — the 429 retry path calls this outside any handler."""

    @pytest.mark.parametrize("malformed", ["47..s", ".s", "..", "1m..s", "1h.."])
    def test_malformed_returns_none(self, malformed):
        assert _parse_duration(malformed) is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1m26.4s", 86.4), ("90", 90.0), ("562ms", 0.562), ("1h2m", 3720.0)],
    )
    def test_wellformed_still_parses(self, value, expected):
        assert _parse_duration(value) == pytest.approx(expected)


class TestThrottleHonorsFullWait:
    """The old clamp slept min(wait, max_sleep) ONCE and then sent anyway:
    with a daily budget exhausted until UTC midnight that meant a doomed
    request (and a fresh 429) every 65 seconds for hours."""

    @pytest.mark.asyncio
    async def test_full_wait_is_slept_in_chunks(self, monkeypatch):
        import maistro_rsi.rate_pacer as pacer_mod

        clock = {"now": 0.0}
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock["now"] += seconds

        monkeypatch.setattr(pacer_mod.time, "monotonic", lambda: clock["now"])
        monkeypatch.setattr(pacer_mod.asyncio, "sleep", fake_sleep)

        pacer = RatePacer(provider_key="test-provider", max_sleep=65.0)
        monkeypatch.setattr(pacer, "_required_wait", lambda: 300.0)

        await pacer._throttle_before()

        assert sum(sleeps) >= 300.0
        assert max(sleeps) <= 65.0
        assert len(sleeps) >= 5  # chunked, not one clamped sleep

    @pytest.mark.asyncio
    async def test_no_wait_means_no_sleep(self, monkeypatch):
        import maistro_rsi.rate_pacer as pacer_mod

        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr(pacer_mod.asyncio, "sleep", fake_sleep)
        pacer = RatePacer(provider_key="test-provider")
        monkeypatch.setattr(pacer, "_required_wait", lambda: 0.0)
        await pacer._throttle_before()
        assert sleeps == []

    @pytest.mark.asyncio
    async def test_hostile_reset_header_is_capped(self, monkeypatch):
        """A garbage/hostile reset of 10^9 seconds must not park the loop
        forever — the total wait is ceilinged at ~25h."""
        import maistro_rsi.rate_pacer as pacer_mod

        clock = {"now": 0.0}
        total = {"slept": 0.0}

        async def fake_sleep(seconds: float) -> None:
            total["slept"] += seconds
            clock["now"] += seconds

        monkeypatch.setattr(pacer_mod.time, "monotonic", lambda: clock["now"])
        monkeypatch.setattr(pacer_mod.asyncio, "sleep", fake_sleep)

        pacer = RatePacer(provider_key="test-provider", max_sleep=3600.0)
        pacer._last = pacer_mod.RateSnapshot(
            remaining_tokens=0.0, limit_tokens=1000.0, reset_seconds=1e9
        )
        await pacer._throttle_before()
        assert total["slept"] <= RatePacer._MAX_TOTAL_WAIT_S + 3600.0
