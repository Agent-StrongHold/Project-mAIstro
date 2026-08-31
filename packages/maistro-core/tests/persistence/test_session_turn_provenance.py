"""A session turn names the execution that produced it (#748).

The link existed before this, but only as a coincidence: `container.py` passes
`run.run_id` as the `turn_id`, and `turn_id` is contractually an opaque
idempotency key -- `reject_blank_turn_id` is its whole definition, and any
caller may pass any non-empty string. These tests hold the *stated* fact, in
columns that mean it, on all three backends. A twin that drops what PostgreSQL
persists passes every test written against the twin alone (#696 found three
such drops in one store).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from maistro.observability.correlation import bind_execution_context
from maistro.persistence.pg_sessions import PgSessionStore
from maistro.persistence.sqlite_sessions import SqliteSessionStore
from maistro.sessions.store import InMemorySessionStore

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]

_BATCH = [{"role": "user", "content": "hello"}]


class _Backend:
    """A session store plus the one thing each backend answers differently."""

    def __init__(self, store: Any, name: str, read_marker: Any) -> None:
        self.store = store
        self.name = name
        self._read_marker = read_marker

    async def marker(self, session_id: str, turn_id: str) -> tuple[Any, Any, Any] | None:
        """The turn's recorded producer, or None when no such turn exists."""
        return await self._read_marker(session_id, turn_id)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    if request.param == "memory":
        store = InMemorySessionStore()

        async def read_memory(session_id: str, turn_id: str) -> tuple[Any, Any, Any] | None:
            held = store.turn_provenance(session_id, turn_id)
            if held is None:
                return None
            return held.as_columns()

        yield _Backend(store, "memory", read_memory)
        return

    if request.param == "sqlite":
        conn = await aiosqlite.connect(":memory:")
        sqlite_store = SqliteSessionStore(conn)
        await sqlite_store.ensure_schema()

        async def read_sqlite(session_id: str, turn_id: str) -> tuple[Any, Any, Any] | None:
            cursor = await conn.execute(
                "SELECT run_id, node_run_id, attempt_id FROM session_turns "
                "WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            )
            row = await cursor.fetchone()
            return None if row is None else (row[0], row[1], row[2])

        try:
            yield _Backend(sqlite_store, "sqlite", read_sqlite)
        finally:
            await conn.close()
        return

    if pg_pool is None:
        pytest.skip("set MAISTRO_TEST_PG_DSN to run the PostgreSQL parametrization")

    async def read_pg(session_id: str, turn_id: str) -> tuple[Any, Any, Any] | None:
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT run_id, node_run_id, attempt_id FROM session_turns "
                "WHERE session_id = $1 AND turn_id = $2",
                session_id,
                turn_id,
            )
        return None if row is None else (row["run_id"], row["node_run_id"], row["attempt_id"])

    yield _Backend(PgSessionStore(pg_pool), "postgres", read_pg)


class TestATurnNamesItsExecution:
    @pytest.mark.ac("SPEC-083026-56ee/AC-1")
    @pytest.mark.ac("SPEC-083026-56ee/AC-2")
    async def test_a_turn_appended_inside_an_execution_records_it(self, backend: Any) -> None:
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            await backend.store.append_messages("sess-1", _BATCH, "turn-1")

        assert await backend.marker("sess-1", "turn-1") == ("r-1", "nr-1", "a-1")

    @pytest.mark.ac("SPEC-083026-56ee/AC-1")
    async def test_the_messages_themselves_are_unchanged(self, backend: Any) -> None:
        """The provenance rides on the marker, not on the conversation. A turn
        appended inside an execution reads back exactly as one appended
        outside it."""
        with bind_execution_context(run_id="r-1"):
            await backend.store.append_messages("sess-1", _BATCH, "turn-1")

        assert await backend.store.get_history("sess-1") == _BATCH

    @pytest.mark.ac("SPEC-083026-56ee/AC-2")
    async def test_a_turn_appended_outside_an_execution_records_absence(self, backend: Any) -> None:
        """`None`, not `""`. An empty string names a Run whose id is empty,
        which is a claim; absence says no execution was in scope."""
        await backend.store.append_messages("sess-1", _BATCH, "turn-1")

        assert await backend.marker("sess-1", "turn-1") == (None, None, None)

    @pytest.mark.ac("SPEC-083026-56ee/AC-2")
    async def test_a_partly_bound_context_records_only_what_it_knows(self, backend: Any) -> None:
        """A seam that resolved a Run and not an Attempt records the Run. The
        alternative -- refusing the whole triple unless all three are known --
        would lose the id it did have."""
        with bind_execution_context(run_id="r-1"):
            await backend.store.append_messages("sess-1", _BATCH, "turn-1")

        assert await backend.marker("sess-1", "turn-1") == ("r-1", None, None)


class TestTheSessionNamesItsRuns:
    @pytest.mark.ac("SPEC-083026-56ee/AC-1")
    async def test_a_sessions_runs_come_back_oldest_first(self, backend: Any) -> None:
        for index, run_id in enumerate(("r-1", "r-2", "r-3")):
            with bind_execution_context(run_id=run_id):
                await backend.store.append_messages("sess-1", _BATCH, f"turn-{index}")

        assert await backend.store.produced_runs("sess-1") == ["r-1", "r-2", "r-3"]

    @pytest.mark.ac("SPEC-083026-56ee/AC-1")
    async def test_one_run_appearing_twice_is_named_once(self, backend: Any) -> None:
        """A Run that retried its turn under a second identity produced one
        Run, not two."""
        for turn in ("turn-1", "turn-2"):
            with bind_execution_context(run_id="r-1"):
                await backend.store.append_messages("sess-1", _BATCH, turn)

        assert await backend.store.produced_runs("sess-1") == ["r-1"]

    @pytest.mark.ac("SPEC-083026-56ee/AC-2")
    async def test_a_turn_with_no_execution_contributes_no_name(self, backend: Any) -> None:
        await backend.store.append_messages("sess-1", _BATCH, "turn-1")
        with bind_execution_context(run_id="r-1"):
            await backend.store.append_messages("sess-1", _BATCH, "turn-2")

        assert await backend.store.produced_runs("sess-1") == ["r-1"]

    @pytest.mark.ac("SPEC-083026-56ee/AC-1")
    async def test_another_sessions_runs_are_not_named(self, backend: Any) -> None:
        with bind_execution_context(run_id="r-other"):
            await backend.store.append_messages("sess-2", _BATCH, "turn-1")

        assert await backend.store.produced_runs("sess-1") == []


class TestTheTurnIdentityKeepsItsMeaning:
    @pytest.mark.ac("SPEC-083026-56ee/AC-3")
    async def test_a_turn_identity_that_is_not_a_run_id_still_dedupes(self, backend: Any) -> None:
        """The retry contract of ADR-083026-5fab is untouched: `turn_id` is
        opaque, and this one deliberately is not a Run id."""
        with bind_execution_context(run_id="r-1"):
            await backend.store.append_messages("sess-1", _BATCH, "not-a-run-id")
            await backend.store.append_messages("sess-1", _BATCH, "not-a-run-id")

        assert await backend.store.get_history("sess-1") == _BATCH
        assert await backend.store.produced_runs("sess-1") == ["r-1"]

    @pytest.mark.ac("SPEC-083026-56ee/AC-3")
    async def test_a_retry_under_a_new_execution_does_not_rewrite_the_producer(
        self, backend: Any
    ) -> None:
        """The second append is a no-op, so the marker keeps the execution that
        actually wrote the messages. Overwriting it would attribute a user's
        words to an Attempt that never appended them."""
        with bind_execution_context(run_id="r-1", attempt_id="a-1"):
            await backend.store.append_messages("sess-1", _BATCH, "turn-1")
        with bind_execution_context(run_id="r-1", attempt_id="a-2"):
            await backend.store.append_messages("sess-1", _BATCH, "turn-1")

        assert await backend.marker("sess-1", "turn-1") == ("r-1", None, "a-1")

    @pytest.mark.ac("SPEC-083026-56ee/AC-3")
    async def test_a_blank_turn_identity_is_still_refused(self, backend: Any) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            await backend.store.append_messages("sess-1", _BATCH, "")

    @pytest.mark.ac("SPEC-083026-56ee/AC-3")
    async def test_an_append_with_no_turn_identity_is_unchanged(self, backend: Any) -> None:
        """Without an identity there is no marker, so there is nowhere to
        record a producer -- and the append is the one it always was."""
        with bind_execution_context(run_id="r-1"):
            await backend.store.append_messages("sess-1", _BATCH)

        assert await backend.store.get_history("sess-1") == _BATCH
        assert await backend.store.produced_runs("sess-1") == []


#: Anything a store would need in order to drive an execution rather than
#: record one. Read off the ADR's claim, not off the current code, so a method
#: added later trips this rather than being grandfathered by it.
_LIFECYCLE_VERBS = ("start", "close", "cancel", "retry", "resume", "admit", "execute", "abort")


class TestTheSessionStoreOwnsNoExecutionLifecycle:
    @pytest.mark.ac("SPEC-083026-56ee/AC-6")
    @pytest.mark.parametrize(
        "store_type", [InMemorySessionStore, SqliteSessionStore, PgSessionStore]
    )
    def test_no_public_method_drives_an_execution(self, store_type: type) -> None:
        """Correlating to a Run is not owning one. The whole point of #64's
        third bullet is that the session store learns which execution wrote a
        turn without acquiring any say over it."""
        offenders = [
            name
            for name, _ in inspect.getmembers(store_type, callable)
            if not name.startswith("_")
            and any(name == verb or name.startswith(f"{verb}_") for verb in _LIFECYCLE_VERBS)
        ]
        assert offenders == []

    @pytest.mark.ac("SPEC-083026-56ee/AC-6")
    async def test_the_run_to_session_direction_is_indexed(self, pg_pool: Any) -> None:
        """The other direction was never missing -- `ChatTurnAdmitter` has
        always written the session into the Run's provenance -- it was
        unindexed, so "the Runs of this session" was a sequential scan of a
        table two sweepers walk. Asserted against `pg_indexes` rather than an
        `EXPLAIN`, whose plan choice depends on how many rows the planner has
        seen and would pass on an empty scratch database either way."""
        if pg_pool is None:
            pytest.skip("set MAISTRO_TEST_PG_DSN to run this")
        async with pg_pool.acquire() as conn:
            definition = await conn.fetchval(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_canonical_runs_session'"
            )
        assert definition is not None, "migration 028 did not create the index"
        assert "'session_id'" in definition
        # Partial: only chat Runs carry a session, and indexing every other
        # Run's NULL would be most of the table for none of the queries.
        assert "WHERE" in definition.upper()


#: The three-column `session_turns` a homelab file created before 028 holds.
#: Spelled out rather than derived from the current schema: a constant that
#: tracked the new table would stop describing the old one the moment it
#: changed, which is the failure this whole class exists to catch.
_PRE_028_TURNS = """
CREATE TABLE session_turns (
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    PRIMARY KEY (session_id, turn_id)
)
"""


class TestAStoreFileFromBeforeTheColumns:
    """`CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it was.

    So a homelab file created before 028 keeps its three-column
    `session_turns`, and every append would fail on the insert -- the failure
    #710 hit on the same shape of change. The `ALTER` path in `ensure_schema`
    exists for this, and on a fresh database it never runs, so nothing
    exercised it until these.
    """

    async def _older_file(self) -> Any:
        conn = await aiosqlite.connect(":memory:")
        await conn.execute(_PRE_028_TURNS)
        await conn.commit()
        return conn

    @pytest.mark.ac("SPEC-083026-56ee/AC-2")
    async def test_ensure_schema_adds_the_columns_an_older_file_lacks(self) -> None:
        conn = await self._older_file()
        try:
            await SqliteSessionStore(conn).ensure_schema()

            cursor = await conn.execute("PRAGMA table_info(session_turns)")
            columns = {row[1] for row in await cursor.fetchall()}
            assert {"run_id", "node_run_id", "attempt_id"} <= columns
        finally:
            await conn.close()

    @pytest.mark.ac("SPEC-083026-56ee/AC-1")
    async def test_an_append_against_an_upgraded_older_file_records_its_run(self) -> None:
        """The point of the `ALTER`: not that the columns exist, but that the
        append which needs them succeeds."""
        conn = await self._older_file()
        try:
            store = SqliteSessionStore(conn)
            await store.ensure_schema()
            with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
                await store.append_messages("sess-1", _BATCH, "turn-1")

            cursor = await conn.execute(
                "SELECT run_id, node_run_id, attempt_id FROM session_turns "
                "WHERE session_id = ? AND turn_id = ?",
                ("sess-1", "turn-1"),
            )
            assert await cursor.fetchone() == ("r-1", "nr-1", "a-1")
        finally:
            await conn.close()

    @pytest.mark.ac("SPEC-083026-56ee/AC-3")
    async def test_rows_written_before_the_upgrade_are_kept(self) -> None:
        """An `ALTER TABLE ADD COLUMN` must not cost the markers already there:
        losing one would let a turn it admitted be appended a second time."""
        conn = await self._older_file()
        try:
            await conn.execute(
                "INSERT INTO session_turns (session_id, turn_id, timestamp) VALUES (?, ?, ?)",
                ("sess-1", "turn-old", 1.0),
            )
            await conn.commit()

            await SqliteSessionStore(conn).ensure_schema()

            cursor = await conn.execute(
                "SELECT turn_id, run_id FROM session_turns WHERE session_id = ?", ("sess-1",)
            )
            assert await cursor.fetchall() == [("turn-old", None)]
        finally:
            await conn.close()

    @pytest.mark.ac("SPEC-083026-56ee/AC-2")
    async def test_ensure_schema_is_idempotent_on_an_already_upgraded_file(self) -> None:
        """Called twice, the second call must take the other side of the branch
        -- `ALTER TABLE ADD COLUMN` on an existing column is an error, not a
        no-op, so an unguarded loop would break every restart."""
        conn = await self._older_file()
        try:
            store = SqliteSessionStore(conn)
            await store.ensure_schema()
            await store.ensure_schema()

            cursor = await conn.execute("PRAGMA table_info(session_turns)")
            names = [row[1] for row in await cursor.fetchall()]
            assert names.count("run_id") == 1
        finally:
            await conn.close()
