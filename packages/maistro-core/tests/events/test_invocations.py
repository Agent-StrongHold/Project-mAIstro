"""Tests for the handler invocation store and idempotency keys (SPEC-070226-b234)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.events.invocations import (
    InMemoryInvocationStore,
    InvocationStatus,
    InvocationStore,
    SqliteInvocationStore,
)


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[InvocationStore]:
    if request.param == "memory":
        yield InMemoryInvocationStore()
    else:
        conn = await aiosqlite.connect(":memory:")
        s = SqliteInvocationStore(conn)
        await s.ensure_schema()
        yield s
        await conn.close()


class TestInvocationStore:
    async def test_get_or_create_creates_pending(self, store: InvocationStore) -> None:
        inv = await store.get_or_create("t1", 1)
        assert inv.status is InvocationStatus.PENDING
        assert inv.attempts == 0
        assert not inv.is_terminal

    @pytest.mark.ac("SPEC-070226-b234/AC-3")
    async def test_get_or_create_is_idempotent(self, store: InvocationStore) -> None:
        inv = await store.get_or_create("t1", 1)
        inv.status = InvocationStatus.SUCCESS
        inv.attempts = 1
        await store.save(inv)
        again = await store.get_or_create("t1", 1)
        assert again.status is InvocationStatus.SUCCESS
        assert again.attempts == 1

    @pytest.mark.ac("SPEC-070226-b234/AC-3")
    async def test_distinct_keys_are_distinct_rows(self, store: InvocationStore) -> None:
        await store.get_or_create("t1", 1)
        await store.get_or_create("t2", 1)
        await store.get_or_create("t1", 2)
        assert len(await store.list_for_event(1)) == 2
        assert len(await store.list_for_event(2)) == 1

    async def test_save_updates_status_and_error(self, store: InvocationStore) -> None:
        inv = await store.get_or_create("t1", 5)
        inv.status = InvocationStatus.RETRYING
        inv.attempts = 2
        inv.last_error = "boom"
        await store.save(inv)
        got = await store.get("t1", 5)
        assert got is not None
        assert got.status is InvocationStatus.RETRYING
        assert got.attempts == 2
        assert got.last_error == "boom"

    async def test_get_missing(self, store: InvocationStore) -> None:
        assert await store.get("t1", 999) is None

    @pytest.mark.ac("SPEC-070226-b234/AC-3")
    async def test_terminal_statuses(self, store: InvocationStore) -> None:
        inv = await store.get_or_create("t1", 1)
        for status, terminal in [
            (InvocationStatus.PENDING, False),
            (InvocationStatus.RETRYING, False),
            (InvocationStatus.SUCCESS, True),
            (InvocationStatus.FAILED, True),
        ]:
            inv.status = status
            assert inv.is_terminal is terminal
