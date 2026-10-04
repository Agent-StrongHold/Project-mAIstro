"""Coverage for maistro.persistence.sqlite_quota.SqliteQuotaTracker against a real
in-memory sqlite3 DB (via aiosqlite) — no mocking needed."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.persistence.pg_quota import cycle_key
from maistro.persistence.sqlite_quota import SqliteQuotaTracker
from maistro.types.model import UnknownBillingCycleError


@pytest.fixture
async def tracker() -> AsyncIterator[SqliteQuotaTracker]:
    conn = await aiosqlite.connect(":memory:")
    t = SqliteQuotaTracker(conn)
    await t.ensure_schema()
    yield t
    await conn.close()


@pytest.mark.asyncio
async def test_record_usage_creates_new_row(tracker: SqliteQuotaTracker) -> None:
    result = await tracker.record_usage("openai", "monthly", 100, 50)
    assert result == {
        "provider": "openai",
        "cycle_key": cycle_key("monthly"),
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "request_count": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("unnormalized", ["Monthly", "  Monthly  ", "MONTHLY"])
async def test_unnormalized_cycle_values_fail_explicitly(
    tracker: SqliteQuotaTracker, unnormalized: str
) -> None:
    """#1205: the old silent fallback landed any unrecognized cycle string in
    the monthly bucket, so '  Monthly  ' quietly worked by accident. The
    tracked vocabulary is exact — anything else fails at the seam."""
    with pytest.raises(UnknownBillingCycleError):
        await tracker.record_usage("openai", unnormalized, 100, 50)


@pytest.mark.asyncio
async def test_record_usage_accumulates_on_conflict(tracker: SqliteQuotaTracker) -> None:
    await tracker.record_usage("openai", "monthly", 100, 50)
    result = await tracker.record_usage("openai", "monthly", 10, 5)
    assert result == {
        "provider": "openai",
        "cycle_key": cycle_key("monthly"),
        "input_tokens": 110,
        "output_tokens": 55,
        "total_tokens": 165,
        "request_count": 2,
    }


@pytest.mark.asyncio
async def test_record_invocation_is_idempotent_and_marks_missing_usage(
    tracker: SqliteQuotaTracker,
) -> None:
    first = await tracker.record_invocation("inv-1", "openai", "monthly", 0, 0, False)
    second = await tracker.record_invocation("inv-1", "openai", "monthly", 99, 1, False)

    assert first["request_count"] == 1
    assert first["unreported_count"] == 1
    assert first["usage_complete"] is False
    assert second == first
    row = (await tracker.get_all_usage())[0]
    assert row["unreported_count"] == 1
    assert row["usage_complete"] is False


@pytest.mark.asyncio
async def test_record_invocation_keeps_reported_usage_provenance_idempotent(
    tracker: SqliteQuotaTracker,
) -> None:
    await tracker.record_invocation("inv-2", "openai", "monthly", 10, 5, True)
    row = await tracker.record_invocation("inv-2", "openai", "monthly", 100, 100, True)

    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 5
    assert row["total_tokens"] == 15
    assert row["request_count"] == 1


@pytest.mark.asyncio
async def test_record_usage_retry_with_same_event_id_counts_once(
    tracker: SqliteQuotaTracker,
) -> None:
    await tracker.record_usage("openai", "monthly", 7, 5, event_id="invocation-1")
    result = await tracker.record_usage("openai", "monthly", 7, 5, event_id="invocation-1")

    assert result["total_tokens"] == 12
    assert result["request_count"] == 1


@pytest.mark.asyncio
async def test_reusing_event_id_with_different_usage_is_rejected(
    tracker: SqliteQuotaTracker,
) -> None:
    await tracker.record_usage("openai", "monthly", 7, 5, event_id="invocation-1")

    with pytest.raises(ValueError, match="event_id"):
        await tracker.record_usage("openai", "monthly", 8, 5, event_id="invocation-1")


@pytest.mark.asyncio
async def test_get_usage_pct_zero_free_tokens_returns_zero(
    tracker: SqliteQuotaTracker,
) -> None:
    assert await tracker.get_usage_pct("openai", "monthly", 0) == 0.0


@pytest.mark.asyncio
async def test_get_usage_pct_negative_free_tokens_returns_zero(
    tracker: SqliteQuotaTracker,
) -> None:
    assert await tracker.get_usage_pct("openai", "monthly", -5) == 0.0


@pytest.mark.asyncio
async def test_get_usage_pct_no_row_returns_zero(tracker: SqliteQuotaTracker) -> None:
    assert await tracker.get_usage_pct("openai", "monthly", 1000) == 0.0


@pytest.mark.asyncio
async def test_get_usage_pct_computes_ratio(tracker: SqliteQuotaTracker) -> None:
    await tracker.record_usage("openai", "monthly", 250, 0)
    pct = await tracker.get_usage_pct("openai", "monthly", 1000)
    assert pct == 0.25


@pytest.mark.asyncio
async def test_get_usage_pct_missing_evidence_is_unknown_not_zero(
    tracker: SqliteQuotaTracker,
) -> None:
    """#718: unreported evidence must not present as 0% used / full headroom
    — the ratio over the reported remainder is unknowable, so the percentage
    is ``None`` (unknown), never a measured zero."""
    await tracker.record_invocation("inv-u1", "openai", "monthly", 0, 0, False)

    assert await tracker.get_usage_pct("openai", "monthly", 100) is None


@pytest.mark.asyncio
async def test_get_usage_pct_mixed_evidence_stays_unknown(
    tracker: SqliteQuotaTracker,
) -> None:
    await tracker.record_invocation("inv-r1", "openai", "monthly", 30, 20, True)
    await tracker.record_invocation("inv-u1", "openai", "monthly", 0, 0, False)

    assert await tracker.get_usage_pct("openai", "monthly", 100) is None


@pytest.mark.asyncio
async def test_get_all_usage_empty(tracker: SqliteQuotaTracker) -> None:
    assert await tracker.get_all_usage() == []


@pytest.mark.asyncio
async def test_get_all_usage_ordered_by_provider_then_cycle_key(
    tracker: SqliteQuotaTracker,
) -> None:
    await tracker.record_usage("openai", "monthly", 1, 1)
    await tracker.record_usage("anthropic", "monthly", 2, 2)
    rows = await tracker.get_all_usage()
    assert [r["provider"] for r in rows] == ["anthropic", "openai"]
