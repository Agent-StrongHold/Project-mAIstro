"""SPEC-083026-ba26: episodic memory against stores that actually persist.

`episodic_memories` had a table, an index and no code. The only `EpisodicStore`
was a list on the heap, and the container wired it whatever the database URL
said — so ADR-080's seven tiers, its reinforcement counts and its weight floors
were all properties of one process's uptime (#710).

These drive the real stores. The PostgreSQL cases refuse to run against
anything but a real server: a fake connection enforces no unique constraint and
no column type, so it cannot fail on the upsert or on a field the migration
forgot, which is most of what is under test here.

"Survives a restart" is shown by a *second store on a second connection* — a
new pool for PostgreSQL, a reopened file for SQLite. Re-reading through the same
object would prove only that the object remembers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.episodic.tiers import clamp_weight
from maistro.persistence.pg_episodic import PgEpisodicStore
from maistro.types.memory import EpisodicMemory, MemoryScope, MemoryTier

from .conftest import postgres_dsn

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]

_LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


def _memory(memory_id: str, **fields: Any) -> EpisodicMemory:
    fields.setdefault("content", f"a note about {memory_id}")
    fields.setdefault("org_id", "org-a")
    fields.setdefault("scope", MemoryScope.ORGANIZATION)
    return EpisodicMemory(memory_id=memory_id, **fields)


async def _sqlite_store(path: str) -> tuple[Any, Any]:
    from maistro.persistence.sqlite_episodic import SqliteEpisodicStore

    conn = await aiosqlite.connect(path)
    store = SqliteEpisodicStore(conn)
    await store.ensure_schema()
    return store, conn


@pytest.fixture
async def sqlite_file(tmp_path: Any) -> AsyncIterator[str]:
    yield str(tmp_path / "episodic.sqlite3")


@pytest.fixture(params=["sqlite", "postgres"])
async def durable_store(
    request: pytest.FixtureRequest, pg_pool: Any, sqlite_file: str
) -> AsyncIterator[Any]:
    """One durable store per backend. Skips PostgreSQL when none is configured."""
    if request.param == "sqlite":
        store, conn = await _sqlite_store(sqlite_file)
        try:
            yield store
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    store = PgEpisodicStore(pg_pool)
    await store.ensure_schema()
    yield store


class TestAMemoryOutlivesItsProcess:
    @pytest.mark.ac("SPEC-083026-ba26/AC-1")
    async def test_a_sqlite_memory_is_there_after_a_reopen(self, sqlite_file: str) -> None:
        store, conn = await _sqlite_store(sqlite_file)
        await store.store(_memory("m1", tier=MemoryTier.LESSON, weight=0.7, reinforcement_count=3))
        await store.reinforce("m1", delta=0.05)
        await conn.close()

        reopened, conn2 = await _sqlite_store(sqlite_file)
        try:
            [found] = await reopened.list_by_scope(org_id="org-a")
        finally:
            await conn2.close()

        assert found.memory_id == "m1"
        assert found.tier is MemoryTier.LESSON
        assert found.reinforcement_count == 4
        assert found.weight == pytest.approx(0.75)

    @pytest.mark.ac("SPEC-083026-ba26/AC-1")
    async def test_a_postgres_memory_is_there_on_another_pool(self, pg_pool: Any) -> None:
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        asyncpg = pytest.importorskip("asyncpg")
        store = PgEpisodicStore(pg_pool)
        await store.ensure_schema()
        await store.store(_memory("m1", tier=MemoryTier.WISDOM, weight=0.9))
        await store.reinforce("m1", delta=0.02)

        other = await asyncpg.create_pool(postgres_dsn(), min_size=1, max_size=2)
        try:
            [found] = await PgEpisodicStore(other).list_by_scope(org_id="org-a")
        finally:
            await other.close()

        assert found.memory_id == "m1"
        assert found.tier is MemoryTier.WISDOM
        assert found.reinforcement_count == 1

    async def test_storing_the_same_id_twice_leaves_one_row(self, durable_store: Any) -> None:
        """`memory_id` is unique on the table, so the second store is an upsert.
        `InMemoryEpisodicStore` appends and would hold two — a difference worth
        pinning, because every other method here addresses a memory by that id
        and two rows would make "the" memory ambiguous."""
        await durable_store.store(_memory("m1", content="first"))
        await durable_store.store(_memory("m1", content="second"))

        found = await durable_store.list_by_scope(org_id="org-a")
        assert [m.content for m in found] == ["second"]


class TestTheRowHoldsTheRecord:
    @pytest.mark.ac("SPEC-083026-ba26/AC-2")
    async def test_the_four_added_fields_survive_the_round_trip(self, durable_store: Any) -> None:
        """`project_id`, `decay_rate`, `shared` and `flagged_for_review` were on
        the dataclass and absent from the table until migration 025."""
        await durable_store.store(
            _memory(
                "m1",
                project_id="proj-1",
                decay_rate=0.5,
                shared=True,
                flagged_for_review=True,
                context={"why": "because"},
                source="a-test",
            )
        )
        [found] = await durable_store.list_by_scope(org_id="org-a")

        assert found.project_id == "proj-1"
        assert found.decay_rate == pytest.approx(0.5)
        assert found.shared is True
        assert found.flagged_for_review is True
        assert found.context == {"why": "because"}
        assert found.source == "a-test"

    @pytest.mark.ac("SPEC-083026-ba26/AC-2")
    async def test_a_memory_stored_with_none_of_them_reads_back_as_the_defaults(
        self, durable_store: Any
    ) -> None:
        await durable_store.store(_memory("m1"))
        [found] = await durable_store.list_by_scope(org_id="org-a")

        assert found.project_id == ""
        assert found.shared is False
        assert found.flagged_for_review is False
        assert found.context == {}
        assert found.decay_rate == pytest.approx(EpisodicMemory().decay_rate)

    async def test_the_timestamps_come_back_aware(self, durable_store: Any) -> None:
        """`tick_decay` subtracts `last_accessed_at` from an aware `now`; a naive
        value there raises. SQLite stores text and has no idea it is a moment,
        so the mapping is where this has to be settled."""
        await durable_store.store(_memory("m1", last_accessed_at=_LONG_AGO))
        [found] = await durable_store.list_by_scope(org_id="org-a")

        assert found.last_accessed_at.tzinfo is not None
        assert found.last_accessed_at == _LONG_AGO

    async def test_a_project_filter_selects_without_a_scope(self, durable_store: Any) -> None:
        await durable_store.store(_memory("m1", project_id="proj-1"))
        await durable_store.store(_memory("m2", project_id="proj-2"))

        found = await durable_store.list_by_scope(project_id="proj-1")
        assert [m.memory_id for m in found] == ["m1"]


class TestScopeFilteringIsTheServersWork:
    @pytest.mark.ac("SPEC-083026-ba26/AC-4")
    async def test_the_plan_applies_the_scope_predicate(self, pg_pool: Any) -> None:
        """`EXPLAIN` on the query that actually runs, built by
        `_scoped_list_query` — the property is that the server filters, and that
        is only visible in a plan. A hand-copied query would prove nothing about
        the one the store issues (#188)."""
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.persistence.pg_episodic import _scoped_list_query

        sql, params = _scoped_list_query(
            agent_id="a1",
            user_id=None,
            team_id=None,
            org_id="org-a",
            project_id=None,
            min_weight=0.0,
            limit=50,
        )
        async with pg_pool.acquire() as conn:
            plan = "\n".join(
                row["QUERY PLAN"] for row in await conn.fetch(f"EXPLAIN {sql}", *params)
            )

        assert "org_id" in plan
        assert "agent_id" in plan

    @pytest.mark.ac("SPEC-083026-ba26/AC-4")
    async def test_a_memory_outside_the_scope_is_never_returned(self, durable_store: Any) -> None:
        await durable_store.store(_memory("mine", org_id="org-a"))
        await durable_store.store(_memory("theirs", org_id="org-b"))
        await durable_store.store(_memory("their-global", org_id="org-b", scope=MemoryScope.GLOBAL))

        found = await durable_store.list_by_scope(org_id="org-a")
        assert [m.memory_id for m in found] == ["mine"]


class TestTheDecayLadderIsDurable:
    @pytest.mark.ac("SPEC-083026-ba26/AC-5")
    async def test_a_sweep_reports_what_the_in_memory_sweep_reports(
        self, durable_store: Any
    ) -> None:
        """Counted against `InMemoryEpisodicStore`, not against numbers written
        into the test. `DecaySweep` distinguishes "decayed" from "at_floor", and
        a memory already resting on its floor is swept without moving — a
        distinction hard-coded expectations get wrong (this test did, first
        time round) and the reference store cannot."""
        volatile = InMemoryEpisodicStore()
        corpus = [
            _memory("observation", tier=MemoryTier.OBSERVATION, weight=0.5),
            _memory("wisdom", tier=MemoryTier.WISDOM, weight=0.9),
            _memory("lesson", tier=MemoryTier.LESSON, weight=0.8),
        ]
        for memory in corpus:
            await volatile.store(memory)
            await durable_store.store(memory)
        moment = datetime.now(UTC) + timedelta(hours=10)

        mine = await durable_store.apply_decay(now=moment)
        theirs = await volatile.apply_decay(now=moment)

        assert mine == theirs
        assert (mine.scanned, mine.decayed, mine.at_floor) == (3, 2, 1)

    @pytest.mark.ac("SPEC-083026-ba26/AC-5")
    async def test_the_decayed_weights_are_still_there_for_the_next_reader(
        self, durable_store: Any
    ) -> None:
        await durable_store.store(_memory("observation", tier=MemoryTier.OBSERVATION, weight=0.5))

        await durable_store.apply_decay(now=datetime.now(UTC) + timedelta(hours=10))

        [found] = await durable_store.list_by_scope(org_id="org-a")
        assert found.weight == pytest.approx(0.4)
        assert found.last_accessed_at > datetime.now(UTC) + timedelta(hours=9)

    @pytest.mark.ac("SPEC-083026-ba26/AC-5")
    async def test_a_wisdom_memory_does_not_fall_below_its_floor(self, durable_store: Any) -> None:
        """The wisdom floor is ADR-080's "structurally unforgettable" promise.
        Making it a property of the database rather than of one process's uptime
        is what #710 is for."""
        floor = clamp_weight(MemoryTier.WISDOM, float("-inf"))
        await durable_store.store(
            _memory("wisdom", tier=MemoryTier.WISDOM, weight=0.9, last_accessed_at=_LONG_AGO)
        )

        sweep = await durable_store.apply_decay()

        [found] = await durable_store.list_by_scope(org_id="org-a")
        assert found.weight == pytest.approx(floor)
        assert sweep.at_floor == 1

    async def test_a_deleted_memory_is_not_swept(self, durable_store: Any) -> None:
        await durable_store.store(_memory("gone", deleted=True))
        assert (await durable_store.apply_decay()).scanned == 0


class TestTheThreeStoresAgree:
    @pytest.mark.ac("SPEC-083026-ba26/AC-6")
    async def test_retrieve_and_list_return_the_same_memories(self, durable_store: Any) -> None:
        volatile = InMemoryEpisodicStore()
        corpus = [
            _memory("alpha", content="postgres notes on indexes", weight=0.8),
            _memory("beta", content="notes on decay", weight=0.6),
            _memory("gamma", content="unrelated", weight=0.4),
            _memory("delta", content="postgres decay notes", weight=0.2),
        ]
        for memory in corpus:
            await volatile.store(memory)
            await durable_store.store(memory)

        assert [
            m.memory_id for m in await durable_store.retrieve("postgres notes", org_id="org-a")
        ] == [m.memory_id for m in await volatile.retrieve("postgres notes", org_id="org-a")]
        assert [m.memory_id for m in await durable_store.list_by_scope(org_id="org-a")] == [
            m.memory_id for m in await volatile.list_by_scope(org_id="org-a")
        ]

    @pytest.mark.ac("SPEC-083026-ba26/AC-6")
    async def test_reinforce_moves_the_weight_the_same_way(self, durable_store: Any) -> None:
        volatile = InMemoryEpisodicStore()
        memory = _memory("m1", tier=MemoryTier.OPINION, weight=0.5)
        await volatile.store(memory)
        await durable_store.store(memory)

        await volatile.reinforce("m1", delta=0.2)
        await durable_store.reinforce("m1", delta=0.2)

        [mine] = await durable_store.list_by_scope(org_id="org-a")
        [theirs] = await volatile.list_by_scope(org_id="org-a")
        assert mine.weight == pytest.approx(theirs.weight)
        assert mine.reinforcement_count == theirs.reinforcement_count

    async def test_reinforcing_a_memory_that_is_not_there_is_not_an_error(
        self, durable_store: Any
    ) -> None:
        """`InMemoryEpisodicStore.reinforce` walks its list and falls off the
        end. The durable stores must do the same rather than raise: the caller
        is a feedback path, and a missing memory is not its failure."""
        await durable_store.reinforce("never-stored", delta=0.1)

    async def test_a_min_weight_floor_selects_the_same_set(self, durable_store: Any) -> None:
        volatile = InMemoryEpisodicStore()
        for memory in (_memory("heavy", weight=0.8), _memory("light", weight=0.1)):
            await volatile.store(memory)
            await durable_store.store(memory)

        assert [
            m.memory_id for m in await durable_store.list_by_scope(org_id="org-a", min_weight=0.5)
        ] == [m.memory_id for m in await volatile.list_by_scope(org_id="org-a", min_weight=0.5)]
