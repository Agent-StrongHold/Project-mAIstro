"""Coverage for maistro.persistence.pg_quota (was 0%)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.persistence.pg_quota import PgQuotaTracker, cycle_key


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

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []


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


def test_cycle_key_strips_and_lowercases() -> None:
    assert cycle_key("  2024-01  ") == "2024-01"
    assert cycle_key("MONTHLY") == "monthly"


@pytest.mark.asyncio
async def test_record_usage_upserts_and_returns_row(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "request_count": 1,
        }
    )
    result = await tracker.record_usage("openai", "  Monthly  ", 100, 50)
    call = conn.calls[0]
    assert call.method == "fetchrow"
    assert "ON CONFLICT (provider, cycle_key) DO UPDATE" in call.query
    assert call.args == ("openai", "monthly", 100, 50, 150)
    assert result == {
        "provider": "openai",
        "cycle_key": "monthly",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "request_count": 1,
    }


@pytest.mark.asyncio
async def test_record_usage_no_row_returns_zero_defaults(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    result = await tracker.record_usage("openai", "monthly", 10, 20)
    assert result == {
        "provider": "openai",
        "cycle_key": "monthly",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
    }


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
    pct = await tracker.get_usage_pct("openai", "Monthly", 1000)
    assert pct == 0.25
    call = conn.calls[0]
    assert call.args == ("openai", "monthly")


@pytest.mark.asyncio
async def test_get_usage_pct_no_row_defaults_total_to_zero(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    pct = await tracker.get_usage_pct("openai", "monthly", 1000)
    assert pct == 0.0


@pytest.mark.asyncio
async def test_get_all_usage_returns_ordered_list(
    tracker: PgQuotaTracker, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "provider": "anthropic",
                "cycle_key": "monthly",
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
            "cycle_key": "monthly",
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
