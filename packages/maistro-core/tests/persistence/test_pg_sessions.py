"""Coverage for maistro.persistence.pg_sessions.PgSessionStore."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.persistence.pg_sessions import PgSessionStore


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class _TransactionCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.transaction_entries += 1

    async def __aexit__(self, *exc: Any) -> None:
        self._conn.transaction_exits += 1


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetch_results: list[list[FakeRecord]] = []
        self._fetchrow_results: list[FakeRecord | None] = []
        self.transaction_entries = 0
        self.transaction_exits = 0

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    def transaction(self) -> _TransactionCtx:
        return _TransactionCtx(self)

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

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
def store(conn: FakeConnection) -> PgSessionStore:
    return PgSessionStore(FakePool(conn))


@pytest.mark.asyncio
async def test_get_history_uses_defaults_and_reverses_desc_rows(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "first"},
        ]
    )
    history = await store.get_history("s1")
    assert history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    call = conn.calls[0]
    assert call.method == "fetch"
    assert call.args[0] == "s1"
    assert call.args[2] == 20


@pytest.mark.asyncio
async def test_get_history_overrides_max_messages_and_ttl(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await store.get_history("s1", max_messages=5, ttl_seconds=60)
    call = conn.calls[0]
    assert call.args[2] == 5


@pytest.mark.asyncio
async def test_get_history_empty_returns_empty_list(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    assert await store.get_history("s1") == []


@pytest.mark.asyncio
async def test_append_messages_locks_and_inserts_one_atomic_batch(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_seq": 3})
    await store.append_messages(
        "s1",
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )

    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    lock_calls = [c for c in conn.calls if "pg_advisory_xact_lock" in c.query]
    insert_calls = [c for c in conn.calls if c.method == "execute" and "INSERT" in c.query]
    purge_calls = [c for c in conn.calls if c.method == "execute" and "DELETE" in c.query]
    assert len(lock_calls) == 1
    assert lock_calls[0].args == ("s1",)
    assert len(purge_calls) == 1
    assert len(insert_calls) == 2
    assert insert_calls[0].args == ("s1", 3, "user", "hi")
    assert insert_calls[1].args == ("s1", 4, "assistant", "hello")
    assert conn.calls.index(lock_calls[0]) < next(
        index for index, call in enumerate(conn.calls) if call.method == "fetchrow"
    )


@pytest.mark.asyncio
async def test_append_messages_drops_non_user_assistant_roles_without_consuming_seq(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_seq": 0})
    await store.append_messages(
        "s1",
        [
            {"role": "system", "content": "ignored"},
            {"role": "user", "content": "kept"},
        ],
    )
    insert_calls = [c for c in conn.calls if c.method == "execute" and "INSERT" in c.query]
    purge_calls = [c for c in conn.calls if c.method == "execute" and "DELETE" in c.query]
    assert len(purge_calls) == 1
    assert len(insert_calls) == 1
    assert insert_calls[0].args == ("s1", 0, "user", "kept")


@pytest.mark.asyncio
async def test_append_messages_defaults_missing_role_and_content_to_empty(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"next_seq": 0})
    await store.append_messages("s1", [{}])
    insert_calls = [c for c in conn.calls if c.method == "execute" and "INSERT" in c.query]
    purge_calls = [c for c in conn.calls if c.method == "execute" and "DELETE" in c.query]
    assert len(purge_calls) == 1
    assert insert_calls == []


@pytest.mark.asyncio
async def test_append_messages_no_existing_rows_starts_seq_at_default(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)
    await store.append_messages("s1", [{"role": "user", "content": "hi"}])
    insert_calls = [c for c in conn.calls if c.method == "execute" and "INSERT" in c.query]
    purge_calls = [c for c in conn.calls if c.method == "execute" and "DELETE" in c.query]
    assert len(purge_calls) == 1
    assert insert_calls[0].args == ("s1", 0, "user", "hi")


@pytest.mark.asyncio
async def test_delete_session_uses_the_same_session_lock(
    store: PgSessionStore, conn: FakeConnection
) -> None:
    await store.delete_session("s1")
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    assert "pg_advisory_xact_lock" in conn.calls[0].query
    delete_call = next(
        c for c in conn.calls if "DELETE FROM sessions WHERE session_id = $1" in c.query
    )
    assert delete_call.args == ("s1",)
