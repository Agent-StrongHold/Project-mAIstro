"""Coverage for maistro.persistence.sqlite_quota.SqliteQuotaTracker against a real
in-memory sqlite3 DB (via aiosqlite) — no mocking needed."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.persistence.pg_quota import cycle_key
from maistro.persistence.sqlite_quota import SqliteQuotaTracker


@pytest.fixture
async def tracker() -> AsyncIterator[SqliteQuotaTracker]:
    conn = await aiosqlite.connect(":memory:")
    t = SqliteQuotaTracker(conn)
    await t.ensure_schema()
    yield t
    await conn.close()


@pytest.mark.asyncio
async def test_record_usage_creates_new_row(tracker: SqliteQuotaTracker) -> None:
    result = await tracker.record_usage("openai", "  Monthly  ", 100, 50)
    assert result == {
        "provider": "openai",
        "cycle_key": cycle_key("monthly"),
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "request_count": 1,
    }


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
    pct = await tracker.get_usage_pct("openai", "Monthly", 1000)
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


@pytest.mark.asyncio
async def test_evidence_and_its_aggregate_commit_together(
    tracker: SqliteQuotaTracker,
) -> None:
    """A crash between the two must not lose the projection permanently.

    The evidence row is the idempotency key: a retry's `ON CONFLICT DO
    NOTHING` reports nothing inserted and therefore skips the projection. So
    committing the evidence *before* projecting left a window in which an
    interruption understated `quota_usage` forever, with no later call able to
    repair it — the retry sees the conflict and does nothing (Codex, #1362).

    Interrupting the projection must therefore roll the evidence back too,
    leaving the invocation genuinely unrecorded and the retry able to redo
    both.
    """

    original = tracker._project_usage_locked

    async def fail_once(*args: object, **kwargs: object) -> None:
        tracker._project_usage_locked = original  # type: ignore[method-assign]
        raise RuntimeError("process died between the evidence row and its aggregate")

    tracker._project_usage_locked = fail_once  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="process died"):
        await tracker.record_invocation("inv-1", "openai", "monthly", 100, 50, True)

    # Nothing was committed: no evidence, no aggregate.
    assert (await tracker.get_all_usage()) == []

    # And the retry records both, because the evidence row is not there to
    # suppress it.
    result = await tracker.record_invocation("inv-1", "openai", "monthly", 100, 50, True)

    assert result["total_tokens"] == 150
    assert result["request_count"] == 1


@pytest.mark.asyncio
async def test_record_unreported_counts_the_call_without_inventing_tokens(
    tracker: SqliteQuotaTracker,
) -> None:
    """A provider that answered but reported no usage still costs a request.

    The counter exists so an operator can tell "this cycle used 150 tokens"
    from "this cycle used 150 tokens *that we know of*". Inventing an estimate
    here would make the aggregate agree with itself and disagree with the bill,
    so the tokens stay at zero and `usage_complete` carries the doubt instead.
    """
    result = await tracker.record_unreported("openai", "  Monthly  ")

    assert result == {
        "provider": "openai",
        "cycle_key": cycle_key("monthly"),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "request_count": 1,
        "unreported_count": 1,
        "usage_complete": False,
    }


@pytest.mark.asyncio
async def test_record_unreported_accumulates_beside_reported_usage(
    tracker: SqliteQuotaTracker,
) -> None:
    """Reported and unreported calls share one row; only the counters differ."""
    await tracker.record_usage("openai", "monthly", 100, 50)
    await tracker.record_unreported("openai", "monthly")
    result = await tracker.record_unreported("openai", "monthly")

    # Three requests, two of them unaccounted, and the 150 reported tokens
    # neither grown nor lost by the two that reported nothing.
    assert result["request_count"] == 3
    assert result["unreported_count"] == 2
    assert result["total_tokens"] == 150
    assert result["usage_complete"] is False


@pytest.mark.asyncio
async def test_record_unreported_is_committed_not_merely_buffered(
    tracker: SqliteQuotaTracker,
) -> None:
    """The projection is durable when the call returns, not at some later flush.

    Read back through a rollback: anything still sitting in an open transaction
    would disappear, so surviving one is what distinguishes a committed write
    from a buffered one.
    """
    await tracker.record_unreported("anthropic", "monthly")
    await tracker._conn.rollback()

    after = await tracker._fetch_usage("anthropic", cycle_key("monthly"))
    assert after["request_count"] == 1
    assert after["unreported_count"] == 1
