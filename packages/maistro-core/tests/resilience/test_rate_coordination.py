from __future__ import annotations

import json
import time

import pytest

from maistro.resilience.rate_coordination import RateLimitCoordinator


class TestInMemoryMode:
    @pytest.mark.ac("ADR-066/AC-23")
    def test_not_limited_initially(self):
        coord = RateLimitCoordinator()
        assert coord.is_rate_limited("openai") is False

    def test_record_and_check(self):
        coord = RateLimitCoordinator()
        reset_at = time.time() + 60
        coord.record_rate_limit("openai", reset_at)
        assert coord.is_rate_limited("openai") is True

    def test_expired_limit_not_limited(self):
        coord = RateLimitCoordinator()
        reset_at = time.time() - 10
        coord.record_rate_limit("openai", reset_at)
        assert coord.is_rate_limited("openai") is False

    def test_get_reset_time_none_when_not_recorded(self):
        coord = RateLimitCoordinator()
        assert coord.get_reset_time("openai") is None

    def test_get_reset_time_returns_timestamp(self):
        coord = RateLimitCoordinator()
        reset_at = time.time() + 60
        coord.record_rate_limit("openai", reset_at)
        assert coord.get_reset_time("openai") == pytest.approx(reset_at, abs=1)

    def test_clear_provider(self):
        coord = RateLimitCoordinator()
        coord.record_rate_limit("openai", time.time() + 60)
        coord.clear("openai")
        assert coord.is_rate_limited("openai") is False
        assert coord.get_reset_time("openai") is None

    def test_clear_all(self):
        coord = RateLimitCoordinator()
        coord.record_rate_limit("openai", time.time() + 60)
        coord.record_rate_limit("anthropic", time.time() + 60)
        coord.clear_all()
        assert coord.is_rate_limited("openai") is False
        assert coord.is_rate_limited("anthropic") is False

    @pytest.mark.ac("ADR-066/AC-29")
    def test_independent_providers(self):
        coord = RateLimitCoordinator()
        coord.record_rate_limit("openai", time.time() + 60)
        assert coord.is_rate_limited("openai") is True
        assert coord.is_rate_limited("anthropic") is False

    def test_clear_one_preserves_other(self):
        coord = RateLimitCoordinator()
        coord.record_rate_limit("openai", time.time() + 60)
        coord.record_rate_limit("anthropic", time.time() + 60)
        coord.clear("openai")
        assert coord.is_rate_limited("openai") is False
        assert coord.is_rate_limited("anthropic") is True


class TestFileMode:
    def test_record_and_check(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        reset_at = time.time() + 60
        coord.record_rate_limit("openai", reset_at)
        assert coord.is_rate_limited("openai") is True

    @pytest.mark.ac("ADR-066/AC-23")
    def test_not_limited_initially(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        assert coord.is_rate_limited("openai") is False

    def test_expired_limit(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        coord.record_rate_limit("openai", time.time() - 10)
        assert coord.is_rate_limited("openai") is False

    def test_clear_provider(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        coord.record_rate_limit("openai", time.time() + 60)
        coord.clear("openai")
        assert coord.is_rate_limited("openai") is False

    def test_clear_all(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        coord.record_rate_limit("openai", time.time() + 60)
        coord.record_rate_limit("anthropic", time.time() + 60)
        coord.clear_all()
        assert coord.is_rate_limited("openai") is False
        assert coord.is_rate_limited("anthropic") is False

    @pytest.mark.ac("ADR-066/AC-29")
    def test_independent_providers(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        coord.record_rate_limit("openai", time.time() + 60)
        assert coord.is_rate_limited("openai") is True
        assert coord.is_rate_limited("anthropic") is False

    def test_clear_one_preserves_other(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        coord.record_rate_limit("openai", time.time() + 60)
        coord.record_rate_limit("anthropic", time.time() + 60)
        coord.clear("openai")
        assert coord.is_rate_limited("openai") is False
        assert coord.is_rate_limited("anthropic") is True

    @pytest.mark.ac("ADR-066/AC-24")
    def test_state_persists_across_instances(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        reset_at = time.time() + 60
        coord1 = RateLimitCoordinator(state_file=state_file)
        coord1.record_rate_limit("openai", reset_at)

        coord2 = RateLimitCoordinator(state_file=state_file)
        assert coord2.is_rate_limited("openai") is True

    def test_file_is_valid_json(self, tmp_path):
        state_file = str(tmp_path / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        coord.record_rate_limit("openai", time.time() + 60)
        with open(state_file) as f:
            data = json.load(f)
        assert "openai" in data

    def test_nonexistent_file(self, tmp_path):
        state_file = str(tmp_path / "nonexistent" / "rates.json")
        coord = RateLimitCoordinator(state_file=state_file)
        assert coord.is_rate_limited("openai") is False
