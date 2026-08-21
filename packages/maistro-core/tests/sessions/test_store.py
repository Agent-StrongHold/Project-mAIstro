"""Tests for maistro.sessions.store.InMemorySessionStore."""

from __future__ import annotations

import time

from maistro.sessions.store import InMemorySessionStore
from maistro.types.session import SessionConfig


class TestGetHistory:
    async def test_empty_session_returns_empty_list(self) -> None:
        store = InMemorySessionStore()
        assert await store.get_history("missing") == []

    async def test_returns_appended_messages_in_order(self) -> None:
        store = InMemorySessionStore()
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

    async def test_respects_max_messages_override(self) -> None:
        store = InMemorySessionStore()
        for i in range(5):
            await store.append_messages("s1", [{"role": "user", "content": str(i)}])

        history = await store.get_history("s1", max_messages=2)

        assert [m["content"] for m in history] == ["3", "4"]

    async def test_uses_config_max_messages_when_not_overridden(self) -> None:
        store = InMemorySessionStore(SessionConfig(max_messages=1))
        await store.append_messages(
            "s1", [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        )

        history = await store.get_history("s1")

        assert [m["content"] for m in history] == ["b"]

    async def test_expired_messages_pruned_by_ttl(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        store._sessions["s1"][0] = (
            store._sessions["s1"][0][0],
            "user",
            "old",
            time.time() - 1000,
        )

        history = await store.get_history("s1", ttl_seconds=10)

        assert history == []

    async def test_uses_config_ttl_when_not_overridden(self) -> None:
        store = InMemorySessionStore(SessionConfig(ttl_seconds=5))
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        store._sessions["s1"][0] = (
            store._sessions["s1"][0][0],
            "user",
            "old",
            time.time() - 1000,
        )

        history = await store.get_history("s1")

        assert history == []


class TestAppendMessages:
    async def test_skips_messages_with_invalid_role(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "kept"},
            ],
        )

        history = await store.get_history("s1")

        assert history == [{"role": "user", "content": "kept"}]

    async def test_skips_messages_with_non_string_content(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": 123},
                {"role": "user", "content": "ok"},
            ],
        )

        history = await store.get_history("s1")

        assert history == [{"role": "user", "content": "ok"}]

    async def test_missing_role_and_content_default_to_empty(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{}])

        history = await store.get_history("s1")

        assert history == []

    async def test_appended_messages_prune_expired_entries(self) -> None:
        store = InMemorySessionStore(SessionConfig(ttl_seconds=1000))
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        store._sessions["s1"][0] = (
            store._sessions["s1"][0][0],
            "user",
            "old",
            time.time() - 2000,
        )

        await store.append_messages("s1", [{"role": "user", "content": "new"}])

        history = await store.get_history("s1")

        assert history == [{"role": "user", "content": "new"}]


class TestDeleteSession:
    async def test_delete_removes_session_data(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hi"}])

        await store.delete_session("s1")

        assert await store.get_history("s1") == []
        assert "s1" not in store._sessions
        assert "s1" not in store._next_seq

    async def test_delete_nonexistent_session_is_noop(self) -> None:
        store = InMemorySessionStore()
        await store.delete_session("missing")

        assert store._sessions == {}
        assert store._next_seq == {}
