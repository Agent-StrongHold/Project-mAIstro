"""Tests for maistro.quota.billing and maistro.quota.tracker."""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.quota.billing import cycle_key, daily_budget
from maistro.quota.tracker import InMemoryQuotaTracker


class TestCycleKey:
    def test_daily_returns_date_string(self) -> None:
        expected = datetime.now(UTC).strftime("%Y-%m-%d")
        assert cycle_key("daily") == expected

    def test_monthly_returns_month_string(self) -> None:
        expected = datetime.now(UTC).strftime("%Y-%m")
        assert cycle_key("monthly") == expected

    def test_unknown_cycle_falls_back_to_monthly(self) -> None:
        expected = datetime.now(UTC).strftime("%Y-%m")
        assert cycle_key("weekly") == expected


class TestDailyBudget:
    def test_daily_returns_full_amount(self) -> None:
        assert daily_budget(3000, "daily") == 3000.0

    def test_monthly_divides_by_thirty(self) -> None:
        assert daily_budget(3000, "monthly") == 100.0

    def test_other_cycle_divides_by_thirty(self) -> None:
        assert daily_budget(300, "weekly") == 10.0


class TestInMemoryQuotaTracker:
    async def test_record_usage_initializes_and_accumulates(self) -> None:
        tracker = InMemoryQuotaTracker()

        result = await tracker.record_usage("openai", "daily", 100, 50)

        assert result["provider"] == "openai"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50
        assert result["total_tokens"] == 150
        assert result["request_count"] == 1

    async def test_record_usage_accumulates_across_calls(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("openai", "daily", 100, 50)

        result = await tracker.record_usage("openai", "daily", 10, 5)

        assert result["input_tokens"] == 110
        assert result["output_tokens"] == 55
        assert result["total_tokens"] == 165
        assert result["request_count"] == 2

    async def test_record_usage_separate_keys_for_different_providers(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("openai", "daily", 100, 50)
        await tracker.record_usage("anthropic", "daily", 10, 5)

        usages = await tracker.get_all_usage()
        providers = {u["provider"]: u for u in usages}

        assert providers["openai"]["total_tokens"] == 150
        assert providers["anthropic"]["total_tokens"] == 15

    async def test_get_usage_pct_zero_free_tokens_returns_zero(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("openai", "daily", 100, 50)

        pct = await tracker.get_usage_pct("openai", "daily", 0)

        assert pct == 0.0

    async def test_get_usage_pct_negative_free_tokens_returns_zero(self) -> None:
        tracker = InMemoryQuotaTracker()

        pct = await tracker.get_usage_pct("openai", "daily", -10)

        assert pct == 0.0

    async def test_get_usage_pct_computes_ratio(self) -> None:
        tracker = InMemoryQuotaTracker()
        await tracker.record_usage("openai", "daily", 50, 50)

        pct = await tracker.get_usage_pct("openai", "daily", 200)

        assert pct == 0.5

    async def test_get_all_usage_empty_when_no_records(self) -> None:
        tracker = InMemoryQuotaTracker()
        assert await tracker.get_all_usage() == []
