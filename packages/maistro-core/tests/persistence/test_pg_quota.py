"""Coverage for maistro.persistence.pg_quota (was 0%)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.persistence.pg_quota import PgQuotaTracker, cycle_key
from maistro.quota.billing import cycle_key as canonical_cycle_key
from maistro.types.model import UnknownBillingCycleError


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetchrow_results: list[FakeRecord | None] = []
        self._fetch_results: list[list[FakeRecord]] = []
        self._fetchval_results: list[str | None] = []

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    def queue_fetchval(self, value: str | None) -> None:
        self._fetchval_results.append(value)

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def fetchval(self, query: str, *args: Any) -> str | None:
        self.calls.append(Call("fetchval", query, args))
        return self._fetchval_results.pop(0) if self._fetchval_results else None


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def tracker(conn: FakeConnection) -> PgQuotaTracker:
    return PgQuotaTracker(FakePool(conn))


def test_cycle_key_resolves_the_cycle_running_now() -> None:
    """`billing_cycle` is a cycle *type*, not an instance (#122).

    `ModelQuota.billing_cycle` defaults to `"monthly"` and
    `QuotaBurnScheduler` passes that string straight through, so a key of
    `"monthly"` meant every month accumulated into one row and nothing ever
    rolled over -- a provider that exhausted its free tier once stayed over
    quota permanently. The old assertions here pinned exactly that
    (`cycle_key("MONTHLY") == "monthly"`).

    Compared against `maistro.quota.billing.cycle_key` rather than a literal:
    that function is the contract `InMemoryQuotaTracker` already implements,
    and a hardcoded `"2026-08"` would start failing next month.
    """
    assert cycle_key("monthly") == canonical_cycle_key("monthly")
    assert cycle_key("daily") == canonical_cycle_key("daily")
    # #1205: the tracked vocabulary is exact — 'MONTHLY' is not a tolerated
    # spelling of monthly, it fails instead of landing in the monthly bucket.
    with pytest.raises(UnknownBillingCycleError):
        cycle_key("MONTHLY")
    # Distinct keys per cycle type is the property that makes rollover work.
    assert cycle_key("daily") != cycle_key("monthly")


@pytest.mark.asyncio
async def test_record_usage_upserts_and_returns_row(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"event_id": "event-1"})
    conn.queue_fetchrow(
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "request_count": 1,
        }
    )
    result = await tracker.record_usage("openai", "monthly", 100, 50, event_id="event-1")
    call = conn.calls[0]
    assert call.method == "fetchrow"
    assert "quota_usage_events" in call.query
    assert call.args == ("event-1", "openai", canonical_cycle_key("monthly"), 100, 50)
    assert result == {
        "provider": "openai",
        "cycle_key": canonical_cycle_key("monthly"),
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "request_count": 1,
    }


@pytest.mark.asyncio
async def test_record_usage_no_row_returns_zero_defaults(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"event_id": "event-1"})
    conn.queue_fetchrow(None)
    result = await tracker.record_usage("openai", "monthly", 10, 20, event_id="event-1")
    assert result == {
        "provider": "openai",
        "cycle_key": canonical_cycle_key("monthly"),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }


@pytest.mark.asyncio
async def test_record_usage_conflicting_retry_with_same_payload_counts_once(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """The crash-ambiguous retry: the INSERT conflicts (RETURNING gave no row),
    the stored event matches, so the retry must not double-count."""
    conn.queue_fetchrow(None)  # ON CONFLICT DO NOTHING -> RETURNING is empty
    conn.queue_fetchrow(
        {
            "provider": "openai",
            "cycle_key": canonical_cycle_key("monthly"),
            "input_tokens": 100,
            "output_tokens": 50,
        }
    )
    conn.queue_fetchrow(
        {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "request_count": 1}
    )
    result = await tracker.record_usage("openai", "monthly", 100, 50, event_id="event-1")
    assert result["request_count"] == 1
    assert result["total_tokens"] == 150


@pytest.mark.asyncio
async def test_record_usage_conflicting_retry_with_different_payload_is_rejected(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """A stored identity re-submitted with different usage must be rejected,
    not silently counted again or overwritten."""
    conn.queue_fetchrow(None)  # ON CONFLICT DO NOTHING -> RETURNING is empty
    conn.queue_fetchrow(
        {
            "provider": "openai",
            "cycle_key": canonical_cycle_key("monthly"),
            "input_tokens": 100,
            "output_tokens": 50,
        }
    )
    with pytest.raises(ValueError, match="event_id"):
        await tracker.record_usage("openai", "monthly", 111, 50, event_id="event-1")


@pytest.mark.asyncio
async def test_record_usage_conflicting_retry_with_vanished_row_is_rejected(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """A conflict whose event row cannot be read back is treated as a reuse
    with different usage, never as a silently successful retry."""
    conn.queue_fetchrow(None)  # ON CONFLICT DO NOTHING -> RETURNING is empty
    conn.queue_fetchrow(None)  # ... and the SELECT finds no stored row either
    with pytest.raises(ValueError, match="event_id"):
        await tracker.record_usage("openai", "monthly", 100, 50, event_id="event-1")


@pytest.mark.asyncio
async def test_get_usage_pct_zero_free_tokens_returns_zero_without_query(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    pct = await tracker.get_usage_pct("openai", "monthly", 0)
    assert pct == 0.0
    assert conn.calls == []


@pytest.mark.asyncio
async def test_get_usage_pct_negative_free_tokens_returns_zero(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    pct = await tracker.get_usage_pct("openai", "monthly", -5)
    assert pct == 0.0
    assert conn.calls == []


@pytest.mark.asyncio
async def test_get_usage_pct_computes_ratio(tracker: PgQuotaTracker, conn: FakeConnection) -> None:
    conn.queue_fetchrow({"total_tokens": 250})
    pct = await tracker.get_usage_pct("openai", "monthly", 1000)
    assert pct == 0.25
    call = conn.calls[0]
    assert call.args == ("openai", canonical_cycle_key("monthly"))


@pytest.mark.asyncio
async def test_get_usage_pct_no_row_defaults_total_to_zero(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    pct = await tracker.get_usage_pct("openai", "monthly", 1000)
    assert pct == 0.0


@pytest.mark.asyncio
async def test_get_usage_pct_missing_evidence_is_unknown_not_zero(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """#718: a row with unreported evidence must not present ``0.0`` used /
    full headroom — the ratio over the reported remainder is unknowable, so
    the percentage is ``None`` (unknown), never a measured zero."""
    conn.queue_fetchrow({"total_tokens": 0, "unreported_count": 1})
    pct = await tracker.get_usage_pct("openai", "monthly", 100)
    assert pct is None


@pytest.mark.asyncio
async def test_get_usage_pct_mixed_evidence_stays_unknown(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """Reported neighbours do not repair completeness: the unreported call's
    tokens are still missing, so a ratio would understate spend."""
    conn.queue_fetchrow({"total_tokens": 50, "unreported_count": 1})
    pct = await tracker.get_usage_pct("openai", "monthly", 100)
    assert pct is None


@pytest.mark.asyncio
async def test_get_all_usage_returns_ordered_list(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "provider": "anthropic",
                "cycle_key": canonical_cycle_key("monthly"),
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "request_count": 4,
            }
        ]
    )
    result = await tracker.get_all_usage()
    call = conn.calls[0]
    assert "ORDER BY provider, cycle_key" in call.query
    assert result == [
        {
            "provider": "anthropic",
            "cycle_key": canonical_cycle_key("monthly"),
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
            "request_count": 4,
        }
    ]


@pytest.mark.asyncio
async def test_get_all_usage_empty(tracker: PgQuotaTracker, conn: FakeConnection) -> None:
    conn.queue_fetch([])
    result = await tracker.get_all_usage()
    assert result == []


@pytest.mark.asyncio
async def test_record_invocation_reported_usage_inserts_evidence_then_aggregate(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """A first-time Invocation: the evidence row inserts, so the aggregate
    upsert runs and the reported usage is returned (#718)."""
    conn.queue_fetchval("inv-1")  # INSERT ... ON CONFLICT DO NOTHING RETURNING
    conn.queue_fetchrow(
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "request_count": 1}
    )
    result = await tracker.record_invocation(
        "inv-1", "openai", "monthly", 10, 5, usage_reported=True
    )
    evidence_call = conn.calls[0]
    assert evidence_call.method == "fetchval"
    assert "quota_invocation_evidence" in evidence_call.query
    assert "ON CONFLICT (invocation_id) DO NOTHING" in evidence_call.query
    assert evidence_call.args == (
        "inv-1",
        "openai",
        canonical_cycle_key("monthly"),
        10,
        5,
        True,
    )
    # The aggregate upsert charges the tokens exactly once for this evidence.
    upsert_call = conn.calls[1]
    assert "ON CONFLICT (provider, cycle_key)" in upsert_call.query
    assert result == {
        "provider": "openai",
        "cycle_key": canonical_cycle_key("monthly"),
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "request_count": 1,
    }


@pytest.mark.asyncio
async def test_record_invocation_missing_usage_projects_unreported_evidence(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """A completed call whose provider never reported usage: the aggregate
    gains a request and an unreported marker, never a zero-token measurement."""
    conn.queue_fetchval("inv-2")
    conn.queue_fetchrow(
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "request_count": 1,
            "unreported_count": 1,
        }
    )
    result = await tracker.record_invocation(
        "inv-2", "openai", "monthly", 0, 0, usage_reported=False
    )
    unreported_call = conn.calls[1]
    assert "unreported_count" in unreported_call.query
    assert result["request_count"] == 1
    assert result["unreported_count"] == 1
    assert result["usage_complete"] is False


@pytest.mark.asyncio
async def test_record_invocation_duplicate_returns_existing_without_recounting(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """A retry of an already-evidenced Invocation: the INSERT conflicts, so
    only the current aggregate row is read back -- no double-count."""
    conn.queue_fetchval(None)  # ON CONFLICT DO NOTHING -> no row returned
    conn.queue_fetchrow(
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "request_count": 1}
    )
    result = await tracker.record_invocation(
        "inv-1", "openai", "monthly", 999, 999, usage_reported=True
    )
    select_call = conn.calls[1]
    assert select_call.method == "fetchrow"
    assert select_call.query.startswith("SELECT * FROM quota_usage")
    assert result["total_tokens"] == 15
    assert result["request_count"] == 1


@pytest.mark.asyncio
async def test_record_unreported_increments_missing_evidence_counter(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    """Direct unreported projection: one more request, one more unreported
    marker, zero invented tokens."""
    conn.queue_fetchrow(
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "request_count": 2,
            "unreported_count": 2,
        }
    )
    result = await tracker.record_unreported("openai", "monthly")
    call = conn.calls[0]
    assert "unreported_count" in call.query
    assert call.args == ("openai", canonical_cycle_key("monthly"))
    assert result["request_count"] == 2
    assert result["unreported_count"] == 2
    assert result["usage_complete"] is False
