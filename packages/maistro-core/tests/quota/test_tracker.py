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

    async def test_record_invocation_counts_once_per_invocation_id(self) -> None:
        """The tracker's own at-most-once guard (#718): terminalization retries
        hand the same physical Invocation back, and the ledger must ignore it
        even when the caller (a recorder without its own dedup) sends it twice."""
        tracker = InMemoryQuotaTracker()

        first = await tracker.record_invocation("inv-1", "openai", "daily", 10, 5, True)
        second = await tracker.record_invocation("inv-1", "openai", "daily", 10, 5, True)

        assert first == second
        assert first["total_tokens"] == 15
        assert first["request_count"] == 1

    async def test_record_invocation_missing_usage_is_unreported_not_zero(self) -> None:
        tracker = InMemoryQuotaTracker()

        result = await tracker.record_invocation("inv-2", "openai", "daily", 0, 0, False)

        assert result["request_count"] == 1
        assert result["total_tokens"] == 0
        assert result["unreported_count"] == 1
        assert result["usage_complete"] is False

    async def test_get_usage_pct_missing_evidence_is_unknown_not_zero(self) -> None:
        """#718: the verifier's false-complete reproduction. A provider/cycle
        whose calls could not report usage must not present ``0.0`` used with
        full headroom — the ratio over the reported remainder is unknowable,
        so the percentage is ``None`` (unknown), never a measured zero."""
        tracker = InMemoryQuotaTracker()

        await tracker.record_invocation("inv-u1", "openai", "daily", 0, 0, False)

        assert await tracker.get_usage_pct("openai", "daily", 100) is None

    async def test_get_usage_pct_mixed_evidence_stays_unknown(self) -> None:
        """One reported call does not repair the cycle's completeness: the
        unreported call's tokens are still missing, so the ratio would
        understate spend while reading as complete."""
        tracker = InMemoryQuotaTracker()

        await tracker.record_invocation("inv-r1", "openai", "daily", 50, 50, True)
        await tracker.record_invocation("inv-u1", "openai", "daily", 0, 0, False)

        assert await tracker.get_usage_pct("openai", "daily", 200) is None

    async def test_get_usage_pct_no_evidence_at_all_is_a_measured_zero(self) -> None:
        """No call ever recorded is vacuously complete — ``0.0``, distinct from
        the ``None`` that marks calls whose usage went unreported. The read
        also must not fabricate a zero usage row for the provider."""
        tracker = InMemoryQuotaTracker()

        assert await tracker.get_usage_pct("never-called", "daily", 100) == 0.0
        assert await tracker.get_all_usage() == []

    async def test_get_usage_pct_reported_evidence_keeps_computing_ratio(self) -> None:
        tracker = InMemoryQuotaTracker()

        await tracker.record_invocation("inv-r1", "openai", "daily", 50, 50, True)

        assert await tracker.get_usage_pct("openai", "daily", 200) == 0.5


class TestDefaultQuotaTrackerSingleton:
    async def test_registered_tracker_is_returned_until_cleared(self) -> None:
        from maistro.quota.tracker import (
            get_default_quota_tracker,
            set_default_quota_tracker,
        )

        # Save/restore: container-creating tests in the same process register
        # their own default via the composition root, so the ambient value is
        # not asserted — only this test's own registration round-trip is.
        previous = get_default_quota_tracker()
        tracker = InMemoryQuotaTracker()
        try:
            set_default_quota_tracker(tracker)
            assert get_default_quota_tracker() is tracker
        finally:
            set_default_quota_tracker(previous)
