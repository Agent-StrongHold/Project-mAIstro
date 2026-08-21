"""Tests for jittered exponential backoff."""

from __future__ import annotations

from maistro.resilience.backoff import BackoffConfig, compute_backoff, jittered_backoff


class TestJitteredBackoff:
    def test_attempt_zero_returns_zero(self):
        assert jittered_backoff(0) == 0.0

    def test_attempt_negative_returns_zero(self):
        assert jittered_backoff(-1) == 0.0

    def test_attempt_one_near_base(self):
        result = jittered_backoff(1, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert result == 1.0

    def test_attempt_two_doubles(self):
        result = jittered_backoff(2, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert result == 2.0

    def test_attempt_three_quadruples(self):
        result = jittered_backoff(3, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert result == 4.0

    def test_capped_at_max_delay(self):
        result = jittered_backoff(20, base_delay=1.0, max_delay=30.0, jitter_factor=0.0)
        assert result == 30.0

    def test_jitter_adds_randomness(self):
        results = {jittered_backoff(3) for _ in range(100)}
        assert len(results) > 1

    def test_jitter_never_exceeds_max(self):
        for _ in range(1000):
            result = jittered_backoff(10, base_delay=1.0, max_delay=10.0)
            assert result <= 10.0

    def test_jitter_always_positive(self):
        for attempt in range(1, 20):
            for _ in range(100):
                result = jittered_backoff(attempt)
                assert result > 0


class TestComputeBackoff:
    def test_retry_after_override(self):
        config = BackoffConfig(base_delay=1.0, max_delay=60.0)
        result = compute_backoff(1, config, retry_after=10.0)
        assert result == 10.0

    def test_retry_after_exceeds_max(self):
        config = BackoffConfig(max_delay=30.0)
        result = compute_backoff(1, config, retry_after=3600.0)
        assert result == -1.0

    def test_retry_after_capped(self):
        config = BackoffConfig(max_delay=10.0)
        result = compute_backoff(1, config, retry_after=20.0)
        assert result == -1.0

    def test_no_retry_after_uses_jitter(self):
        config = BackoffConfig(base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        result = compute_backoff(3, config)
        assert result == 4.0

    def test_default_config(self):
        config = BackoffConfig()
        result = compute_backoff(1, config, retry_after=5.0)
        assert result == 5.0
