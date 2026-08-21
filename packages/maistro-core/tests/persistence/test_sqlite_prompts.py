"""Coverage for maistro.persistence.sqlite_prompts.SqlitePromptManager against a real
in-memory sqlite3 DB (via aiosqlite)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.persistence.sqlite_prompts import SqlitePromptManager


@pytest.fixture
async def mgr() -> AsyncIterator[SqlitePromptManager]:
    conn = await aiosqlite.connect(":memory:")
    m = SqlitePromptManager(conn)
    await m.ensure_schema()
    yield m
    await conn.close()


@pytest.mark.asyncio
async def test_get_with_config_missing_prompt_returns_empty(mgr: SqlitePromptManager) -> None:
    content, config = await mgr.get_with_config("missing")
    assert content == ""
    assert config == {}


@pytest.mark.asyncio
async def test_upsert_first_version_no_label_promotes_to_latest_and_production(
    mgr: SqlitePromptManager,
) -> None:
    await mgr.upsert("greeting", "hello world", config={"x": 1})
    content, config = await mgr.get_with_config("greeting", label="production")
    assert content == "hello world"
    assert config == {"x": 1}
    latest_content, _ = await mgr.get_with_config("greeting", label="latest")
    assert latest_content == "hello world"


@pytest.mark.asyncio
async def test_upsert_with_explicit_label(mgr: SqlitePromptManager) -> None:
    await mgr.upsert("greeting", "v1")
    await mgr.upsert("greeting", "v2-staging", label="staging")
    content, _ = await mgr.get_with_config("greeting", label="staging")
    assert content == "v2-staging"
    # production label was set by the first (v1) upsert and is untouched by v2.
    prod_content, _ = await mgr.get_with_config("greeting", label="production")
    assert prod_content == "v1"


@pytest.mark.asyncio
async def test_upsert_explicit_label_clears_previous_holder_of_that_label(
    mgr: SqlitePromptManager,
) -> None:
    await mgr.upsert("greeting", "v1", label="staging")
    await mgr.upsert("greeting", "v2", label="staging")
    content, _ = await mgr.get_with_config("greeting", label="staging")
    assert content == "v2"


@pytest.mark.asyncio
async def test_get_falls_back_to_latest_version_when_label_not_found(
    mgr: SqlitePromptManager,
) -> None:
    await mgr.upsert("greeting", "v1")
    await mgr.upsert("greeting", "v2", label="staging")
    # "production" label still points at v1; request a label that's never been set.
    content = await mgr.get("greeting", label="nonexistent")
    assert content == "v2"


@pytest.mark.asyncio
async def test_get_returns_only_content_not_config(mgr: SqlitePromptManager) -> None:
    await mgr.upsert("greeting", "hello", config={"temp": 0.7})
    content = await mgr.get("greeting", label="production")
    assert content == "hello"


@pytest.mark.asyncio
async def test_upsert_first_version_with_production_label_skips_double_insert(
    mgr: SqlitePromptManager,
) -> None:
    await mgr.upsert("greeting", "hello", label="production")
    content, _ = await mgr.get_with_config("greeting", label="production")
    assert content == "hello"


@pytest.mark.asyncio
async def test_upsert_default_config_is_empty_dict(mgr: SqlitePromptManager) -> None:
    await mgr.upsert("greeting", "text")
    _, config = await mgr.get_with_config("greeting", label="production")
    assert config == {}


@pytest.mark.asyncio
async def test_version_increments_across_upserts(mgr: SqlitePromptManager) -> None:
    await mgr.upsert("greeting", "v1")
    await mgr.upsert("greeting", "v2")
    await mgr.upsert("greeting", "v3")
    content = await mgr.get_with_config("greeting", label="latest")
    assert content[0] == "v3"
