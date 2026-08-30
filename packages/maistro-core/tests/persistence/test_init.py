"""Tests for maistro.persistence — pool lifecycle + migration runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import maistro.persistence as persistence_module
from maistro.persistence import close_pool, get_pool, run_migrations


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class FakeConnection:
    def __init__(self, *, has_tables: bool = False) -> None:
        self.calls: list[Call] = []
        self._applied: list[FakeRecord] = []
        self._has_tables = has_tables

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return list(self._applied)

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append(Call("fetchval", query, args))
        return self._has_tables


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
        self.closed = False

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_pool() -> None:
    """Empty the per-DSN registry around every test (#335)."""
    persistence_module._pools.clear()
    yield
    persistence_module._pools.clear()


class TestGetPool:
    @pytest.mark.asyncio
    async def test_creates_pool_on_first_call(self) -> None:
        fake_pool = FakePool(FakeConnection())
        with patch(
            "maistro.persistence.asyncpg.create_pool",
            new=AsyncMock(return_value=fake_pool),
        ) as mock_create:
            pool = await get_pool("postgres://user:pass@host/db")
        assert pool is fake_pool
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reuses_existing_pool(self) -> None:
        fake_pool = FakePool(FakeConnection())
        with patch(
            "maistro.persistence.asyncpg.create_pool",
            new=AsyncMock(return_value=fake_pool),
        ) as mock_create:
            first = await get_pool("postgres://user:pass@host/db")
            second = await get_pool("postgres://user:pass@host/db")
        assert first is second
        mock_create.assert_awaited_once()


class TestClosePool:
    @pytest.mark.asyncio
    async def test_closes_existing_pool(self) -> None:
        fake_pool = FakePool(FakeConnection())
        with patch(
            "maistro.persistence.asyncpg.create_pool",
            new=AsyncMock(return_value=fake_pool),
        ):
            await get_pool("postgres://user:pass@host/db")
        await close_pool()
        assert fake_pool.closed is True
        assert persistence_module._pools == {}

    @pytest.mark.asyncio
    async def test_noop_when_no_pool(self) -> None:
        await close_pool()
        assert persistence_module._pools == {}


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_explicit_dir_missing_warns_and_returns(self, tmp_path: Path) -> None:
        conn = FakeConnection()
        pool = FakePool(conn)
        missing_dir = tmp_path / "nope"
        await run_migrations(pool, migrations_dir=str(missing_dir))
        assert conn.calls == []

    @pytest.mark.asyncio
    async def test_no_dir_given_falls_back_to_default_candidate(self) -> None:
        conn = FakeConnection()
        pool = FakePool(conn)
        await run_migrations(pool, migrations_dir="")
        assert conn.calls == []

    @pytest.mark.asyncio
    async def test_no_dir_given_uses_first_existing_candidate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "migrations").mkdir()
        (tmp_path / "migrations" / "001_init.sql").write_text("CREATE TABLE x (id INT);")
        monkeypatch.chdir(tmp_path)
        conn = FakeConnection(has_tables=False)
        pool = FakePool(conn)

        await run_migrations(pool, migrations_dir="")

        execute_queries = [c.query for c in conn.calls if c.method == "execute"]
        assert "CREATE TABLE x (id INT);" in execute_queries

    @pytest.mark.asyncio
    async def test_applies_new_migrations_when_no_pre_existing_tables(self, tmp_path: Path) -> None:
        (tmp_path / "001_init.sql").write_text("CREATE TABLE x (id INT);")
        (tmp_path / "002_add.sql").write_text("ALTER TABLE x ADD y INT;")
        conn = FakeConnection(has_tables=False)
        pool = FakePool(conn)

        await run_migrations(pool, migrations_dir=str(tmp_path))

        execute_queries = [c.query for c in conn.calls if c.method == "execute"]
        assert "CREATE TABLE x (id INT);" in execute_queries
        assert "ALTER TABLE x ADD y INT;" in execute_queries
        insert_calls = [c for c in conn.calls if "INSERT INTO _migrations" in c.query]
        assert len(insert_calls) == 2

    @pytest.mark.asyncio
    async def test_marks_pre_existing_migrations_without_running_sql(self, tmp_path: Path) -> None:
        (tmp_path / "001_init.sql").write_text("CREATE TABLE x (id INT);")
        conn = FakeConnection(has_tables=True)
        pool = FakePool(conn)

        await run_migrations(pool, migrations_dir=str(tmp_path))

        execute_queries = [c.query for c in conn.calls if c.method == "execute"]
        assert "CREATE TABLE x (id INT);" not in execute_queries
        insert_calls = [c for c in conn.calls if "INSERT INTO _migrations" in c.query]
        assert len(insert_calls) == 1
        assert insert_calls[0].args == ("001_init.sql",)

    @pytest.mark.asyncio
    async def test_skips_already_applied_migrations(self, tmp_path: Path) -> None:
        (tmp_path / "001_init.sql").write_text("CREATE TABLE x (id INT);")
        (tmp_path / "002_add.sql").write_text("ALTER TABLE x ADD y INT;")
        conn = FakeConnection(has_tables=False)
        conn._applied = [FakeRecord(name="001_init.sql")]
        pool = FakePool(conn)

        await run_migrations(pool, migrations_dir=str(tmp_path))

        execute_queries = [c.query for c in conn.calls if c.method == "execute"]
        assert "CREATE TABLE x (id INT);" not in execute_queries
        assert "ALTER TABLE x ADD y INT;" in execute_queries
