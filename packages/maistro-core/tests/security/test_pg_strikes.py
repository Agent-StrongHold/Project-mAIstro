"""Coverage for PgStrikeTracker / PgRateLimiter (mocked asyncpg pool boundary)."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.security.pg_strikes import LOCKOUT_DURATION, PgRateLimiter, PgStrikeTracker


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class _TxnCtx:
    async def __aenter__(self) -> _TxnCtx:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetchrow_results: list[FakeRecord | None] = []

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def execute(self, query: str, *args: Any) -> None:
        self.calls.append(Call("execute", query, args))

    def transaction(self) -> _TxnCtx:
        return _TxnCtx()


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self.execute_calls: list[str] = []

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)

    async def execute(self, query: str, *args: Any) -> None:
        self.execute_calls.append(query)

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        return await self._conn.fetchrow(query, *args)


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def fake_pool(conn: FakeConnection) -> FakePool:
    return FakePool(conn)


@pytest.fixture
def patch_asyncpg(monkeypatch: pytest.MonkeyPatch, fake_pool: FakePool) -> FakePool:
    fake_asyncpg = types.ModuleType("asyncpg")

    async def create_pool(*args: Any, **kwargs: Any) -> FakePool:
        return fake_pool

    fake_asyncpg.create_pool = create_pool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
    return fake_pool


async def test_get_pool_creates_and_caches_pool(
    patch_asyncpg: FakePool, fake_pool: FakePool
) -> None:
    tracker = PgStrikeTracker(db_url="postgres://x")
    pool1 = await tracker._get_pool()
    pool2 = await tracker._get_pool()
    assert pool1 is fake_pool
    assert pool2 is fake_pool
    assert tracker._pool is fake_pool


async def test_get_pool_raises_and_logs_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_asyncpg = types.ModuleType("asyncpg")

    async def create_pool(*args: Any, **kwargs: Any) -> FakePool:
        raise RuntimeError("connection refused")

    fake_asyncpg.create_pool = create_pool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

    tracker = PgStrikeTracker(db_url="postgres://x")
    with pytest.raises(RuntimeError, match="connection refused"):
        await tracker._get_pool()


def test_init_uses_explicit_db_url_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://env")
    tracker = PgStrikeTracker(db_url="postgres://explicit")
    assert tracker._db_url == "postgres://explicit"


def test_init_falls_back_to_database_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEPLOY_TARGET_DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://env-db")
    tracker = PgStrikeTracker()
    assert tracker._db_url == "postgres://env-db"


def test_init_falls_back_to_deploy_target_db_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEPLOY_TARGET_DB_URL", "postgres://deploy-target")
    tracker = PgStrikeTracker()
    assert tracker._db_url == "postgres://deploy-target"


async def test_record_violation_first_strike_sets_elevated(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"user_id": "u1", "strike_count": 1, "scrutiny_level": "elevated"})
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.record_violation(user_id="u1", flags=("flag_a",), detail="d")
    assert result == {"user_id": "u1", "strike_count": 1, "escalated": True}
    executed_queries = [c.query for c in conn.calls if c.method == "execute"]
    assert any("scrutiny_level='elevated'" in q for q in executed_queries)


async def test_record_violation_second_strike_locks_account(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"user_id": "u1", "strike_count": 2})
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.record_violation(user_id="u1", flags=("flag_a", "flag_b"))
    assert result["strike_count"] == 2
    executed_queries = [c.query for c in conn.calls if c.method == "execute"]
    assert any("scrutiny_level='locked'" in q for q in executed_queries)


async def test_record_violation_third_strike_disables_account(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"user_id": "u1", "strike_count": 3})
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.record_violation(user_id="u1", flags=("flag_a",))
    assert result["strike_count"] == 3
    executed_queries = [c.query for c in conn.calls if c.method == "execute"]
    assert any("disabled=TRUE" in q for q in executed_queries)


async def test_record_violation_inserts_violation_row_with_truncated_detail(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"user_id": "u1", "strike_count": 1})
    tracker = PgStrikeTracker(db_url="postgres://x")
    long_detail = "x" * 2000
    await tracker.record_violation(
        user_id="u1", flags=("f",), boundary="tool_result", detail=long_detail
    )
    insert_calls = [
        c
        for c in conn.calls
        if c.method == "execute" and "INSERT INTO security_violations" in c.query
    ]
    assert len(insert_calls) == 1
    args = insert_calls[0].args
    assert args[0] == "u1"
    assert args[1] == ["f"]
    assert args[2] == "tool_result"
    assert args[3] == long_detail[:1000]
    assert len(args[3]) == 1000


async def test_get_returns_none_for_unknown_user(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.get("ghost")
    assert result is None


async def test_get_marks_disabled_user_as_locked(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"user_id": "u1", "disabled": True, "locked_until": None})
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.get("u1")
    assert result is not None
    assert result["is_locked"] is True


async def test_get_marks_user_with_future_lockout_as_locked(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    conn.queue_fetchrow({"user_id": "u1", "disabled": False, "locked_until": future})
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.get("u1")
    assert result is not None
    assert result["is_locked"] is True


async def test_get_marks_user_with_expired_lockout_as_not_locked(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    conn.queue_fetchrow({"user_id": "u1", "disabled": False, "locked_until": past})
    tracker = PgStrikeTracker(db_url="postgres://x")
    result = await tracker.get("u1")
    assert result is not None
    assert result["is_locked"] is False


async def test_is_locked_returns_false_for_unknown_user(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    tracker = PgStrikeTracker(db_url="postgres://x")
    assert await tracker.is_locked("ghost") is False


async def test_is_locked_returns_true_for_disabled_user(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"user_id": "u1", "disabled": True, "locked_until": None})
    tracker = PgStrikeTracker(db_url="postgres://x")
    assert await tracker.is_locked("u1") is True


def test_lockout_duration_is_eight_hours() -> None:
    assert timedelta(hours=8) == LOCKOUT_DURATION


async def test_rate_limiter_get_pool_creates_and_caches(
    patch_asyncpg: FakePool, fake_pool: FakePool
) -> None:
    limiter = PgRateLimiter(db_url="postgres://x")
    pool1 = await limiter._get_pool()
    pool2 = await limiter._get_pool()
    assert pool1 is fake_pool
    assert pool2 is fake_pool


def test_rate_limiter_init_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEPLOY_TARGET_DB_URL", raising=False)
    limiter = PgRateLimiter()
    assert limiter._db_url is None
    assert limiter._window_seconds == 60
    assert limiter._max_requests == 60


async def test_rate_limiter_check_and_record_allows_under_limit(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"count": 1})
    limiter = PgRateLimiter(db_url="postgres://x", max_requests=5)
    allowed, current = await limiter.check_and_record("key1")
    assert allowed is True
    assert current == 1


async def test_rate_limiter_check_and_record_blocks_over_limit(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"count": 10})
    limiter = PgRateLimiter(db_url="postgres://x", max_requests=5)
    allowed, current = await limiter.check_and_record("key1")
    assert allowed is False
    assert current == 10


async def test_rate_limiter_check_and_record_allows_exactly_at_limit(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"count": 5})
    limiter = PgRateLimiter(db_url="postgres://x", max_requests=5)
    allowed, current = await limiter.check_and_record("key1")
    assert allowed is True
    assert current == 5


async def test_rate_limiter_check_and_record_deletes_expired_windows(
    patch_asyncpg: FakePool, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"count": 1})
    limiter = PgRateLimiter(db_url="postgres://x")
    await limiter.check_and_record("key1")
    delete_calls = [
        c
        for c in conn.calls
        if c.method == "execute" and "DELETE FROM security_rate_limits" in c.query
    ]
    assert len(delete_calls) == 1
