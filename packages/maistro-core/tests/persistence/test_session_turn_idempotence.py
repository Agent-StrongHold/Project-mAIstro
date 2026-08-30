"""SPEC-083026-5fab: a retried turn appends its session messages once.

Parametrized over all three stores for the behaviour they must share. The
in-memory store is included deliberately rather than left as "just a double":
most of the suite runs against it, so a double that cannot reproduce a retry is
a double that hides one.

Two criteria are PostgreSQL-only and say so. AC-8 asserts what the *database*
refuses when a writer skips the store's guard entirely, which is the whole
reason the marker is a key rather than a `SELECT` — SQLite's twin is checked
for the same key separately, against its own connection. AC-7 forces a failure
partway through a batch, which needs a column type that can reject a value.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from typing import Any, cast

import asyncpg
import pytest

from maistro.persistence.pg_sessions import PgSessionStore
from maistro.sessions.store import InMemorySessionStore

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]

TURN = [
    {"role": "user", "content": "what is the capital of France"},
    {"role": "assistant", "content": "Paris"},
]


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def session_store(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[Any]:
    if request.param == "memory":
        yield InMemorySessionStore()
        return
    if request.param == "sqlite":
        from maistro.persistence.sqlite_sessions import SqliteSessionStore

        conn = await aiosqlite.connect(":memory:")
        store = SqliteSessionStore(conn)
        await store.ensure_schema()
        try:
            yield store
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    yield PgSessionStore(pg_pool)


class TestAnAppendWithoutAnIdentityIsUnchanged:
    """AC-1. The guarantee is opt-in, and opting out must cost nothing."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-1")
    async def test_the_same_batch_twice_is_recorded_twice(self, session_store: Any) -> None:
        await session_store.append_messages("s", TURN)
        await session_store.append_messages("s", TURN)

        history = await session_store.get_history("s")
        assert [m["content"] for m in history] == [
            "what is the capital of France",
            "Paris",
            "what is the capital of France",
            "Paris",
        ]

    @pytest.mark.ac("SPEC-083026-5fab/AC-1")
    async def test_an_identified_append_does_not_disturb_the_sequence(
        self, session_store: Any
    ) -> None:
        # Ordering is #327's other half, and a marker written beside the
        # messages must not perturb it: an identified batch between two
        # unidentified ones stays in the middle.
        await session_store.append_messages("s", [{"role": "user", "content": "first"}])
        await session_store.append_messages(
            "s", [{"role": "user", "content": "second"}], "turn-1"
        )
        await session_store.append_messages("s", [{"role": "user", "content": "third"}])

        history = await session_store.get_history("s")
        assert [m["content"] for m in history] == ["first", "second", "third"]


class TestARepeatedIdentityAppendsNothing:
    """AC-2 and AC-3: the retry, and that identity alone decides."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-2")
    async def test_the_identical_batch_is_stored_once(self, session_store: Any) -> None:
        await session_store.append_messages("s", TURN, "turn-1")
        await session_store.append_messages("s", TURN, "turn-1")

        history = await session_store.get_history("s")
        assert [m["content"] for m in history] == ["what is the capital of France", "Paris"]

    @pytest.mark.ac("SPEC-083026-5fab/AC-2")
    async def test_the_second_append_raises_nothing(self, session_store: Any) -> None:
        # A retry is not an error. Raising here would make every caller that
        # retries have to distinguish "already done" from "failed", which is
        # the distinction the store is being asked to make on their behalf.
        await session_store.append_messages("s", TURN, "turn-1")
        await session_store.append_messages("s", TURN, "turn-1")

    @pytest.mark.ac("SPEC-083026-5fab/AC-3")
    async def test_different_content_under_a_spent_identity_is_refused(
        self, session_store: Any
    ) -> None:
        # The store deduplicates on identity, never on content — the mirror of
        # why it must not deduplicate on content alone.
        await session_store.append_messages("s", TURN, "turn-1")
        await session_store.append_messages(
            "s", [{"role": "user", "content": "something else entirely"}], "turn-1"
        )

        history = await session_store.get_history("s")
        assert [m["content"] for m in history] == ["what is the capital of France", "Paris"]


class TestAnIdentityIsScopedToItsSession:
    """AC-4. Two conversations that happen to be retried under one Run's id
    are two conversations, and the key says so."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-4")
    async def test_the_same_identity_in_another_session_is_recorded(
        self, session_store: Any
    ) -> None:
        await session_store.append_messages("session-a", TURN, "turn-1")
        await session_store.append_messages("session-b", TURN, "turn-1")

        assert len(await session_store.get_history("session-a")) == 2
        assert len(await session_store.get_history("session-b")) == 2


class TestTheMarkerDoesNotOutliveItsMessages:
    """AC-5. A marker left behind by the retention sweep would suppress a turn
    whose messages no longer exist — silent data loss, arrived at by way of a
    fix for silent duplication."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-5")
    async def test_a_purged_turn_can_be_appended_again(self, session_store: Any) -> None:
        await session_store.append_messages("s", TURN, "turn-1")
        await _purge_everything(session_store)
        assert await session_store.get_history("s") == []

        await session_store.append_messages("s", TURN, "turn-1")

        assert len(await session_store.get_history("s")) == 2


class TestDeletingASessionForgetsItsTurns:
    """AC-6. A reused session id must not inherit the deleted session's
    markers, or its first turn vanishes."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-6")
    async def test_a_recreated_session_accepts_the_same_identity(
        self, session_store: Any
    ) -> None:
        await session_store.append_messages("s", TURN, "turn-1")
        await session_store.delete_session("s")

        await session_store.append_messages("s", TURN, "turn-1")

        assert len(await session_store.get_history("s")) == 2

    @pytest.mark.ac("SPEC-083026-5fab/AC-6")
    async def test_another_session_keeps_its_own_identity(self, session_store: Any) -> None:
        # `delete_session` deletes one session's markers, not every marker
        # sharing its turn id: the delete is keyed on the pair, as the append is.
        await session_store.append_messages("keep", TURN, "turn-1")
        await session_store.append_messages("drop", TURN, "turn-1")
        await session_store.delete_session("drop")

        await session_store.append_messages("keep", TURN, "turn-1")

        assert len(await session_store.get_history("keep")) == 2


class TestABlankIdentityIsRefused:
    """An empty string reads as absent everywhere `or` is used, so accepting
    one would mean an append that believes it is protected and is not."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-2")
    async def test_the_empty_string_is_not_an_identity(self, session_store: Any) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            await session_store.append_messages("s", TURN, "")

        assert await session_store.get_history("s") == []


async def _purge_everything(store: Any) -> None:
    """Expire every message the store holds.

    All three take an explicit zero, which each documents as "purge through
    now" — the value `or` would have swallowed.
    """
    await store.purge_expired(0)


class TestTheMarkerAndTheMessagesCommitTogether:
    """AC-7. A batch that fails partway must leave the identity free, or the
    retry the identity exists to permit is refused for a turn never written."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-7")
    async def test_a_failed_batch_leaves_the_identity_free(self, pg_pool: Any) -> None:
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        store = PgSessionStore(pg_pool)
        invalid = cast(
            list[dict[str, str]],
            [
                {"role": "user", "content": "must-roll-back"},
                {"role": "assistant", "content": object()},
            ],
        )

        with pytest.raises(asyncpg.DataError):
            await store.append_messages("s", invalid, "turn-1")

        assert await pg_pool.fetchval("SELECT count(*) FROM sessions WHERE session_id = 's'") == 0
        assert (
            await pg_pool.fetchval("SELECT count(*) FROM session_turns WHERE session_id = 's'")
            == 0
        )

        await store.append_messages("s", TURN, "turn-1")
        assert len(await store.get_history("s")) == 2

    @pytest.mark.ac("SPEC-083026-5fab/AC-7")
    async def test_a_failed_sqlite_batch_leaves_the_identity_free(self) -> None:
        from maistro.persistence.sqlite_sessions import SqliteSessionStore

        conn = await aiosqlite.connect(":memory:")
        store = SqliteSessionStore(conn)
        await store.ensure_schema()
        invalid = cast(
            list[dict[str, str]],
            [
                {"role": "user", "content": "must-roll-back"},
                {"role": "assistant", "content": object()},
            ],
        )
        try:
            with pytest.raises(sqlite3.ProgrammingError):
                await store.append_messages("s", invalid, "turn-1")

            assert await store.get_history("s") == []
            await store.append_messages("s", TURN, "turn-1")
            assert len(await store.get_history("s")) == 2
        finally:
            await conn.close()


class TestTheDatabaseRefusesADuplicateIdentityOnItsOwn:
    """AC-8. The store's guard runs under a lock that makes it race-free, so
    the key is redundant for that path — which is the point. It is what holds
    when a second write path forgets the lock."""

    @pytest.mark.ac("SPEC-083026-5fab/AC-8")
    async def test_postgres_rejects_a_second_marker(self, pg_pool: Any) -> None:
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        await PgSessionStore(pg_pool).append_messages("s", TURN, "turn-1")

        with pytest.raises(asyncpg.UniqueViolationError):
            await pg_pool.execute(
                "INSERT INTO session_turns (session_id, turn_id) VALUES ($1, $2)",
                "s",
                "turn-1",
            )

    @pytest.mark.ac("SPEC-083026-5fab/AC-8")
    async def test_sqlite_rejects_a_second_marker(self) -> None:
        from maistro.persistence.sqlite_sessions import SqliteSessionStore

        conn = await aiosqlite.connect(":memory:")
        store = SqliteSessionStore(conn)
        await store.ensure_schema()
        try:
            await store.append_messages("s", TURN, "turn-1")

            with pytest.raises(sqlite3.IntegrityError):
                await conn.execute(
                    "INSERT INTO session_turns (session_id, turn_id, timestamp) VALUES (?, ?, ?)",
                    ("s", "turn-1", 0.0),
                )
        finally:
            await conn.close()
