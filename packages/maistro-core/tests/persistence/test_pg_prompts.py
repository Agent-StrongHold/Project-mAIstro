"""Coverage for maistro.persistence.pg_prompts.PgPromptManager (was 0%)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from maistro.persistence.pg_prompts import PgPromptManager, _parse_config


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

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "OK"


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
def mgr(conn: FakeConnection) -> PgPromptManager:
    return PgPromptManager(FakePool(conn))


def test_parse_config_none_returns_empty_dict() -> None:
    assert _parse_config(None) == {}


def test_parse_config_str_parses_json() -> None:
    assert _parse_config('{"a": 1}') == {"a": 1}


def test_parse_config_dict_returns_copy() -> None:
    original = {"a": 1}
    result = _parse_config(original)
    assert result == original
    assert result is not original


def test_parse_config_other_type_returns_empty_dict() -> None:
    assert _parse_config(42) == {}


@pytest.mark.asyncio
async def test_get_with_config_finds_label_match_first(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"content": "hello", "config": '{"temp": 0.5}'})
    content, config = await mgr.get_with_config("greeting", label="production")
    assert content == "hello"
    assert config == {"temp": 0.5}
    call = conn.calls[0]
    assert "WHERE name = $1 AND label = $2" in call.query
    assert call.args == ("greeting", "production")


@pytest.mark.asyncio
async def test_get_with_config_falls_back_to_latest_version_when_no_label_match(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    conn.queue_fetchrow({"content": "fallback", "config": None})
    content, config = await mgr.get_with_config("greeting", label="staging")
    assert content == "fallback"
    assert config == {}
    assert len(conn.calls) == 2
    second_call = conn.calls[1]
    assert "ORDER BY version DESC LIMIT 1" in second_call.query
    assert second_call.args == ("greeting",)


@pytest.mark.asyncio
async def test_get_with_config_no_rows_at_all_returns_empty(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    conn.queue_fetchrow(None)
    content, config = await mgr.get_with_config("missing")
    assert content == ""
    assert config == {}


@pytest.mark.asyncio
async def test_get_delegates_to_get_with_config_and_returns_only_content(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"content": "hi", "config": "{}"})
    content = await mgr.get("greeting", label="production")
    assert content == "hi"


@pytest.mark.asyncio
async def test_upsert_first_version_no_label_promotes_to_latest_and_production(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_ver": 1})
    await mgr.upsert("greeting", "hello world", config={"x": 1})

    execute_calls = [c for c in conn.calls if c.method == "execute"]
    # 1: clear 'latest' label, 2: insert version with label='latest',
    # 3: upsert production row (since next_ver==1 and effective_label != production)
    assert len(execute_calls) == 3

    clear_latest = execute_calls[0]
    assert "SET label = NULL WHERE name = $1 AND label = 'latest'" in clear_latest.query
    assert clear_latest.args == ("greeting",)

    insert_call = execute_calls[1]
    assert "INSERT INTO prompts" in insert_call.query
    assert insert_call.args[0] == "greeting"
    assert insert_call.args[1] == 1
    assert insert_call.args[2] == "latest"
    assert insert_call.args[3] == "hello world"
    assert json.loads(insert_call.args[4]) == {"x": 1}

    production_call = execute_calls[2]
    assert "VALUES ($1, $2, 'production'" in production_call.query
    assert production_call.args == ("greeting", 1, "hello world", json.dumps({"x": 1}))


@pytest.mark.asyncio
async def test_upsert_with_explicit_label_clears_that_label_too(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_ver": 2})
    await mgr.upsert("greeting", "v2", label="staging")

    execute_calls = [c for c in conn.calls if c.method == "execute"]
    # 1: clear 'staging' label, 2: clear 'latest' label, 3: insert (no production
    # promotion since next_ver != 1)
    assert len(execute_calls) == 3
    clear_staging = execute_calls[0]
    assert "SET label = NULL WHERE name = $1 AND label = $2" in clear_staging.query
    assert clear_staging.args == ("greeting", "staging")

    clear_latest = execute_calls[1]
    assert clear_latest.args == ("greeting",)

    insert_call = execute_calls[2]
    assert insert_call.args[2] == "staging"


@pytest.mark.asyncio
async def test_upsert_first_version_with_production_label_skips_double_insert(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_ver": 1})
    await mgr.upsert("greeting", "hello", label="production")

    execute_calls = [c for c in conn.calls if c.method == "execute"]
    # 1: clear 'production' label, 2: clear 'latest' label, 3: insert as production —
    # no extra production-promotion insert since effective_label IS production.
    assert len(execute_calls) == 3
    insert_call = execute_calls[2]
    assert insert_call.args[2] == "production"


@pytest.mark.asyncio
async def test_upsert_no_existing_versions_defaults_next_ver_to_one(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    await mgr.upsert("brand_new", "content")
    execute_calls = [c for c in conn.calls if c.method == "execute"]
    insert_call = execute_calls[1]
    assert insert_call.args[1] == 1


@pytest.mark.asyncio
async def test_upsert_default_config_serializes_empty_dict(
    mgr: PgPromptManager, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_ver": 5})
    await mgr.upsert("greeting", "text")
    execute_calls = [c for c in conn.calls if c.method == "execute"]
    insert_call = execute_calls[1]
    assert json.loads(insert_call.args[4]) == {}
