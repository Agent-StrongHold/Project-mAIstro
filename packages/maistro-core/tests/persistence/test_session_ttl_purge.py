"""Session TTL is enforced by deletion, not only by a read filter (M3).

Both SQL session stores implemented TTL as `timestamp > cutoff` in
`get_history` and never issued a DELETE. Expired conversation content was
therefore hidden from reads but retained forever: the table grew without
bound and user messages outlived their stated lifetime. The only DELETE was
session-id-scoped and nothing scheduled called it.

`security/pg_strikes.py:187-190` already had the right shape — clear the
expired window as part of the normal path rather than deferring to a sweeper
that does not exist.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite
import pytest

from maistro.persistence.pg_sessions import PgSessionStore
from maistro.persistence.sqlite_sessions import SqliteSessionStore


@pytest.fixture
async def store():
    conn = await aiosqlite.connect(":memory:")
    st = SqliteSessionStore(conn, ttl_seconds=100)
    await st.ensure_schema()
    yield st
    await conn.close()


async def _row_count(store: SqliteSessionStore) -> int:
    cursor = await store._conn.execute("SELECT COUNT(*) FROM sessions")
    (n,) = await cursor.fetchone()
    return int(n)


async def _insert_at(store: SqliteSessionStore, session_id: str, seq: int, ts: float) -> None:
    await store._conn.execute(
        "INSERT INTO sessions (session_id, seq, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        (session_id, seq, "user", "secret message", ts),
    )
    await store._conn.commit()


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
async def test_expired_rows_are_deleted_not_merely_hidden(store: SqliteSessionStore) -> None:
    """The core of M3. Fails without the fix: the row is invisible but present.

    Asserting on the row count rather than on `get_history` is the whole
    point — `get_history` filtered correctly *before* the fix too, so a test
    written against it would pass either way and prove nothing.
    """
    await _insert_at(store, "s1", 0, time.time() - 10_000)  # long expired

    assert await _row_count(store) == 1
    assert await store.get_history("s1") == [], "read filter was already working"

    removed = await store.purge_expired()

    assert removed == 1
    assert await _row_count(store) == 0, "expired content was retained on disk"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
async def test_live_rows_survive_the_purge(store: SqliteSessionStore) -> None:
    """Control: the purge must not be a `DELETE FROM sessions`."""
    await _insert_at(store, "s1", 0, time.time())

    await store.purge_expired()

    assert await _row_count(store) == 1
    assert len(await store.get_history("s1")) == 1


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
async def test_append_purges_inline(store: SqliteSessionStore) -> None:
    """A purge method nothing calls repeats the original defect.

    The finding is not "there is no DELETE statement" — it is that nothing
    ever deletes. Adding an unreferenced `purge_expired()` would have left
    that exactly as true, so the purge has to run on the normal path.
    """
    await _insert_at(store, "old", 0, time.time() - 10_000)
    assert await _row_count(store) == 1

    await store.append_messages("new", [{"role": "user", "content": "hi"}])

    remaining = await store._conn.execute("SELECT session_id FROM sessions")
    ids = {r[0] for r in await remaining.fetchall()}
    assert ids == {"new"}, f"expired row survived an append: {ids}"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("unit")
async def test_purge_respects_an_explicit_ttl(store: SqliteSessionStore) -> None:
    await _insert_at(store, "s1", 0, time.time() - 50)

    assert await store.purge_expired(ttl_seconds=1_000) == 0
    assert await store.purge_expired(ttl_seconds=10) == 1


@pytest.fixture(params=["sqlite", "postgres"])
async def turn_store(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[Any]:
    if request.param == "sqlite":
        conn = await aiosqlite.connect(":memory:")
        st = SqliteSessionStore(conn, ttl_seconds=3600)
        await st.ensure_schema()
        try:
            yield st
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    yield PgSessionStore(pg_pool, ttl_seconds=3600)


async def _age_session(store: Any, session_id: str, seconds: float) -> None:
    if isinstance(store, PgSessionStore):
        async with store._pool.acquire() as conn:
            for table in ("sessions", "session_turns"):
                await conn.execute(
                    f"UPDATE {table} SET timestamp = timestamp - make_interval(secs => $2) "
                    "WHERE session_id = $1",
                    session_id,
                    seconds,
                )
        return
    for table in ("sessions", "session_turns"):
        await store._conn.execute(
            f"UPDATE {table} SET timestamp = timestamp - ? WHERE session_id = ?",
            (seconds, session_id),
        )
    await store._conn.commit()


async def _session_ids(store: Any, table: str) -> set[str]:
    query = f"SELECT session_id FROM {table}"
    if isinstance(store, PgSessionStore):
        async with store._pool.acquire() as conn:
            return {r["session_id"] for r in await conn.fetch(query)}
    cursor = await store._conn.execute(query)
    return {r[0] for r in await cursor.fetchall()}


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
async def test_append_past_the_ttl_deletes_expired_messages_and_turn_markers(
    turn_store: Any,
) -> None:
    """The retention inventory records sessions and session_turns as ttl_purge
    driven by append_messages (#325). This is the evidence for that entry, on
    the SQLite twin and on PgSessionStore, the store the PostgreSQL container
    wires: an ordinary append removes rows past the TTL from both tables.
    """
    await turn_store.append_messages("old", [{"role": "user", "content": "hi"}], turn_id="t-old")
    await _age_session(turn_store, "old", 7200)
    assert await _session_ids(turn_store, "sessions") == {"old"}
    assert await _session_ids(turn_store, "session_turns") == {"old"}

    await turn_store.append_messages("new", [{"role": "user", "content": "yo"}], turn_id="t-new")

    assert await _session_ids(turn_store, "sessions") == {"new"}
    assert await _session_ids(turn_store, "session_turns") == {"new"}
