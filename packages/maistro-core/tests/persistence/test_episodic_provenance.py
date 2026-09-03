"""An episodic memory names the execution that stored it (#64).

The one record kind ADR-083026-e602 left out on purpose: `episodic_memories`
had no store behind it, so producer columns would have been a durability claim
with nothing behind them. #710 gave it two durable stores and a wired container
— the condition e602 named for coming back — and this is the follow-up.

Parametrized over every backend for the reason `test_record_provenance.py`
gives: a twin that silently drops what PostgreSQL persists passes every test
written against the twin alone (#696).
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.observability.correlation import bind_execution_context
from maistro.types.memory import EpisodicMemory, MemoryScope, MemoryTier

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]


def _memory(memory_id: str, **fields: Any) -> EpisodicMemory:
    fields.setdefault("content", f"episode {memory_id}")
    fields.setdefault("org_id", "org-1")
    fields.setdefault("scope", MemoryScope.ORGANIZATION)
    return EpisodicMemory(memory_id=memory_id, **fields)


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def episodic(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    if request.param == "memory":
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        yield InMemoryEpisodicStore()
        return
    if request.param == "sqlite":
        from maistro.persistence.sqlite_episodic import SqliteEpisodicStore

        conn = await aiosqlite.connect(":memory:")
        store = SqliteEpisodicStore(conn)
        await store.ensure_schema()
        try:
            yield store, conn
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_episodic import PgEpisodicStore

    store = PgEpisodicStore(pg_pool)
    await store.ensure_schema()
    yield store, pg_pool


async def _stored_row(handle: Any, kind: str, memory_id: str) -> tuple[Any, Any, Any]:
    """The producer columns straight out of the row, not through a mapper.

    A mapper that dropped them would agree with a write that dropped them; the
    row is what a later reader actually has — the same argument
    `test_record_provenance.py` makes for outcomes.
    """
    if kind == "sqlite":
        cursor = await handle.execute(
            "SELECT run_id, node_run_id, attempt_id FROM episodic_memories WHERE memory_id = ?",
            (memory_id,),
        )
        row = await cursor.fetchone()
    else:
        async with handle.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT run_id, node_run_id, attempt_id FROM episodic_memories"
                " WHERE memory_id = $1",
                memory_id,
            )
    return (row[0], row[1], row[2])


class TestAMemoryNamesItsProducer:
    @pytest.mark.ac("SPEC-090226-e4a1/AC-1")
    async def test_a_memory_stored_inside_an_attempt_carries_it(self, episodic: Any) -> None:
        """The caller passes nothing: the store resolves the ids the ambient
        context holds, which is the whole point of #707's context."""
        store = episodic[0] if isinstance(episodic, tuple) else episodic
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            await store.store(_memory("m-inside"))

        [found] = await store.produced_by("r-1", org_id="org-1")
        assert (found.run_id, found.node_run_id, found.attempt_id) == ("r-1", "nr-1", "a-1")

    @pytest.mark.ac("SPEC-090226-e4a1/AC-2")
    async def test_a_memory_stored_outside_an_execution_names_no_producer(
        self, episodic: Any
    ) -> None:
        store = episodic[0] if isinstance(episodic, tuple) else episodic
        await store.store(_memory("m-outside"))

        found = await store.retrieve("episode", org_id="org-1")
        assert found
        assert all(m.run_id == "" for m in found)

    @pytest.mark.ac("SPEC-090226-e4a1/AC-2")
    async def test_a_durable_row_stores_absence_not_an_empty_id(self, episodic: Any) -> None:
        """NULL, not `''`: an empty string reads as a Run whose id is empty,
        which is a claim no memory outside an execution should make."""
        store_and_handle = episodic
        if not isinstance(store_and_handle, tuple):
            pytest.skip("only the durable stores have a row to read")
        store, handle = store_and_handle
        kind = "sqlite" if isinstance(handle, aiosqlite.Connection) else "postgres"
        await store.store(_memory("m-null"))

        assert await _stored_row(handle, kind, "m-null") == (None, None, None)

    @pytest.mark.ac("SPEC-090226-e4a1/AC-3")
    async def test_a_producer_the_caller_named_beats_the_ambient_one(self, episodic: Any) -> None:
        """A memory *about* another execution says something the context does
        not know — the same precedence every provenance-bearing record follows."""
        store = episodic[0] if isinstance(episodic, tuple) else episodic
        with bind_execution_context(run_id="ambient", attempt_id="a-ambient"):
            await store.store(_memory("m-named", run_id="named"))

        assert await store.produced_by("ambient", org_id="org-1") == []
        [found] = await store.produced_by("named", org_id="org-1")
        assert found.attempt_id == "a-ambient"

    @pytest.mark.ac("SPEC-090226-e4a1/AC-4")
    async def test_the_upsert_moves_the_producer_with_the_content(self, episodic: Any) -> None:
        """The upsert replaces the row. Leaving the earlier Run's id on it
        would attribute the surviving content to a Run that no longer wrote it
        — the dedup lesson `InMemoryLearningStore` already learned (#709).

        Durable stores only: `InMemoryEpisodicStore` appends rather than
        upserting, and that divergence is #710's documented contract, not this
        change's to settle.
        """
        if not isinstance(episodic, tuple):
            pytest.skip("the in-memory store appends; the upsert is the durable contract")
        store = episodic[0]
        with bind_execution_context(run_id="r-first"):
            await store.store(_memory("m-upsert", content="first"))
        with bind_execution_context(run_id="r-second"):
            await store.store(_memory("m-upsert", content="second"))

        [found] = await store.produced_by("r-second", org_id="org-1")
        assert found.content == "second"
        assert await store.produced_by("r-first", org_id="org-1") == []


class TestProducedByAnswersOnlyWithinScope:
    @pytest.mark.ac("SPEC-090226-e4a1/AC-5")
    async def test_a_blank_run_id_returns_nothing(self, episodic: Any) -> None:
        """ "Which memories did no execution produce" is a different question,
        and answering it here hands a caller with an unresolved id the wrong
        set."""
        store = episodic[0] if isinstance(episodic, tuple) else episodic
        await store.store(_memory("m-orphan"))
        assert await store.produced_by("", org_id="org-1") == []

    @pytest.mark.ac("SPEC-090226-e4a1/AC-5")
    async def test_provenance_does_not_cross_an_org(self, episodic: Any) -> None:
        """The Run's name must not widen visibility (#844's rule, applied to
        the read this change adds)."""
        store = episodic[0] if isinstance(episodic, tuple) else episodic
        with bind_execution_context(run_id="r-scope"):
            await store.store(_memory("m-org-1", org_id="org-1"))
            await store.store(_memory("m-org-2", org_id="org-2"))

        mine = await store.produced_by("r-scope", org_id="org-1")
        assert [m.memory_id for m in mine] == ["m-org-1"]

    @pytest.mark.ac("SPEC-090226-e4a1/AC-5")
    async def test_a_deleted_memory_is_not_returned(self, episodic: Any) -> None:
        """`retrieve` and `list_by_scope` skip deleted rows; a `produced_by`
        that surfaced them would be a fourth rule for the same fact."""
        store = episodic[0] if isinstance(episodic, tuple) else episodic
        with bind_execution_context(run_id="r-del"):
            memory = _memory("m-deleted", deleted=True)
            await store.store(memory)
            await store.store(_memory("m-live"))

        found = await store.produced_by("r-del", org_id="org-1")
        assert [m.memory_id for m in found] == ["m-live"]


class TestTheVolatileBackendFillsItToo:
    """`memory://` selects this store, so a gap here is a gap nothing else
    catches — `InMemoryLearningStore` states the same reason (#709)."""

    async def test_the_in_memory_store_assigns_provenance_onto_the_record(self) -> None:
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        memory = _memory("m-volatile")
        with bind_execution_context(run_id="r-v", node_run_id="nr-v", attempt_id="a-v"):
            await InMemoryEpisodicStore().store(memory)

        assert (memory.run_id, memory.node_run_id, memory.attempt_id) == ("r-v", "nr-v", "a-v")


# ─── A file created before the columns existed ────────────────────────────────


class TestAnOlderSqliteFileIsUpgradedInPlace:
    """The backup/restore half of #64's promise, for the backend whose
    "restore" is a copied file: a store file written before this change keeps
    its rows and gains the columns, the property SPEC-083026-b2b5/AC-6 pinned
    for learnings."""

    @pytest.mark.ac("SPEC-090226-e4a1/AC-6")
    async def test_existing_rows_survive_the_upgrade(self, tmp_path: Any) -> None:
        from maistro.persistence.sqlite_episodic import SqliteEpisodicStore

        path = tmp_path / "old-episodic.db"
        conn = await aiosqlite.connect(path)
        # The schema exactly as migration 025 + the #710 store left it: no
        # producer columns, because #64 is what adds them.
        await conn.execute(
            """CREATE TABLE episodic_memories (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   memory_id TEXT NOT NULL UNIQUE,
                   tier TEXT NOT NULL DEFAULT 'observation',
                   content TEXT NOT NULL DEFAULT '',
                   weight REAL NOT NULL DEFAULT 0.3,
                   org_id TEXT NOT NULL DEFAULT '',
                   team_id TEXT NOT NULL DEFAULT '',
                   agent_id TEXT,
                   user_id TEXT,
                   scope TEXT NOT NULL DEFAULT 'agent',
                   project_id TEXT NOT NULL DEFAULT '',
                   source TEXT NOT NULL DEFAULT '',
                   context TEXT NOT NULL DEFAULT '{}',
                   reinforcement_count INTEGER NOT NULL DEFAULT 0,
                   contradiction_count INTEGER NOT NULL DEFAULT 0,
                   created_at TEXT NOT NULL DEFAULT '',
                   last_accessed_at TEXT NOT NULL DEFAULT '',
                   deleted INTEGER NOT NULL DEFAULT 0,
                   decay_rate REAL NOT NULL DEFAULT 0.01,
                   shared INTEGER NOT NULL DEFAULT 0,
                   flagged_for_review INTEGER NOT NULL DEFAULT 0
               )"""
        )
        await conn.execute(
            "INSERT INTO episodic_memories (memory_id, content, org_id, scope, created_at,"
            " last_accessed_at) VALUES ('old-1', 'older episode', 'org-1', 'organization',"
            " '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00')"
        )
        await conn.commit()

        store = SqliteEpisodicStore(conn)
        await store.ensure_schema()

        cursor = await conn.execute("PRAGMA table_info(episodic_memories)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert {"run_id", "node_run_id", "attempt_id"} <= columns

        cursor = await conn.execute(
            "SELECT run_id, node_run_id, attempt_id FROM episodic_memories WHERE memory_id = 'old-1'"
        )
        assert await cursor.fetchone() == (None, None, None)

        # The old row is readable through the store, and a new write names its
        # Run — both on the same upgraded file.
        [old] = await store.list_by_scope(org_id="org-1")
        assert old.content == "older episode"
        with bind_execution_context(run_id="r-after"):
            await store.store(_memory("new-1"))
        [new] = await store.produced_by("r-after", org_id="org-1")
        assert new.content == "episode new-1"
        await conn.close()
