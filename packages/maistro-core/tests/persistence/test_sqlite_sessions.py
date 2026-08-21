"""Coverage for maistro.persistence.sqlite_sessions.SqliteSessionStore against a real
in-memory sqlite3 DB (via aiosqlite)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.persistence.sqlite_sessions import SqliteSessionStore


@pytest.fixture
async def store() -> AsyncIterator[SqliteSessionStore]:
    conn = await aiosqlite.connect(":memory:")
    s = SqliteSessionStore(conn)
    await s.ensure_schema()
    yield s
    await conn.close()


@pytest.mark.asyncio
async def test_append_and_get_history_preserves_order(store: SqliteSessionStore) -> None:
    await store.append_messages(
        "s1",
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    history = await store.get_history("s1")
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_append_messages_drops_non_user_assistant_roles(
    store: SqliteSessionStore,
) -> None:
    await store.append_messages(
        "s1",
        [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "kept"},
        ],
    )
    history = await store.get_history("s1")
    assert history == [{"role": "user", "content": "kept"}]


@pytest.mark.asyncio
async def test_get_history_respects_max_messages_limit(store: SqliteSessionStore) -> None:
    await store.append_messages(
        "s1",
        [{"role": "user", "content": str(i)} for i in range(5)],
    )
    history = await store.get_history("s1", max_messages=2)
    assert [m["content"] for m in history] == ["3", "4"]


@pytest.mark.asyncio
async def test_get_history_prunes_expired_messages_via_ttl(
    store: SqliteSessionStore,
) -> None:
    await store.append_messages("s1", [{"role": "user", "content": "old"}])
    history = await store.get_history("s1", ttl_seconds=-1)
    assert history == []


@pytest.mark.asyncio
async def test_get_history_empty_session_returns_empty_list(
    store: SqliteSessionStore,
) -> None:
    assert await store.get_history("missing") == []


@pytest.mark.asyncio
async def test_delete_session_removes_all_messages(store: SqliteSessionStore) -> None:
    await store.append_messages("s1", [{"role": "user", "content": "hi"}])
    await store.delete_session("s1")
    assert await store.get_history("s1") == []


@pytest.mark.asyncio
async def test_sessions_are_independent_by_session_id(store: SqliteSessionStore) -> None:
    await store.append_messages("s1", [{"role": "user", "content": "a"}])
    await store.append_messages("s2", [{"role": "user", "content": "b"}])
    assert await store.get_history("s1") == [{"role": "user", "content": "a"}]
    assert await store.get_history("s2") == [{"role": "user", "content": "b"}]
