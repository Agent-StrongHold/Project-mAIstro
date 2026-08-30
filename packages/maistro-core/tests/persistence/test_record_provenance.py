"""A record names the execution that produced it (#709).

Parametrized over every backend that persists the record kind, for the reason
`test_backend_conformance.py` gives: a twin that silently drops what PostgreSQL
persists passes every test written against the twin alone. #696 found three
such drops in one store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.observability.correlation import (
    ExecutionProvenance,
    bind_execution_context,
    observed_provenance,
)
from maistro.types.memory import Learning, Outcome

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]


async def _sqlite_conn() -> aiosqlite.Connection:
    return await aiosqlite.connect(":memory:")


# ─── The rule itself ──────────────────────────────────────────────────────────


class TestWhatTheCallerNamedWins:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-1")
    def test_an_id_the_caller_supplied_survives_an_ambient_one(self) -> None:
        """A record *about* another execution says something the context does
        not know."""
        with bind_execution_context(run_id="ambient", attempt_id="a-ambient"):
            observed = observed_provenance(run_id="named")
        assert observed.run_id == "named"
        assert observed.attempt_id == "a-ambient"

    @pytest.mark.ac("SPEC-083026-b2b5/AC-1")
    def test_the_context_fills_what_the_caller_left_blank(self) -> None:
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            observed = observed_provenance()
        assert observed == ExecutionProvenance("r-1", "nr-1", "a-1")

    @pytest.mark.ac("SPEC-083026-b2b5/AC-1")
    def test_a_record_made_outside_any_execution_names_none(self) -> None:
        observed = observed_provenance()
        assert observed == ExecutionProvenance()
        assert not observed

    def test_any_one_id_makes_the_provenance_truthy(self) -> None:
        assert ExecutionProvenance(attempt_id="a-1")


# ─── Learnings ────────────────────────────────────────────────────────────────


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def learnings(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    if request.param == "memory":
        from maistro.memory.learnings.store import InMemoryLearningStore

        yield InMemoryLearningStore()
        return
    if request.param == "sqlite":
        from maistro.persistence.sqlite_learnings import SqliteLearningStore

        conn = await _sqlite_conn()
        store = SqliteLearningStore(conn)
        await store.ensure_schema()
        try:
            yield store
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_learnings import PgLearningStore

    store = PgLearningStore(pg_pool)
    await store.ensure_schema()
    yield store


def _learning(**overrides: Any) -> Learning:
    fields: dict[str, Any] = {
        "category": "tool_correction",
        "trigger_keys": ["deploy"],
        "learning": "check the branch first",
        "tool_name": "bash",
        "org_id": "org-1",
    }
    fields.update(overrides)
    return Learning(**fields)


class TestALearningNamesItsProducer:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-2")
    async def test_a_learning_stored_inside_an_attempt_carries_it(self, learnings: Any) -> None:
        """The caller passes nothing. This is the whole point of #707's context:
        the write path several frames below the executor learns the ids for
        free."""
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            await learnings.store(_learning())

        found = await learnings.produced_by("r-1", org_id="org-1")
        assert [(x.run_id, x.node_run_id, x.attempt_id) for x in found] == [("r-1", "nr-1", "a-1")]

    @pytest.mark.ac("SPEC-083026-b2b5/AC-2")
    async def test_a_learning_stored_outside_an_execution_names_no_producer(
        self, learnings: Any
    ) -> None:
        await learnings.store(_learning(trigger_keys=["unrelated"]))
        found = await learnings.find_relevant("unrelated", org_id="org-1")
        assert found
        assert all(x.run_id == "" for x in found)

    @pytest.mark.ac("SPEC-083026-b2b5/AC-5")
    async def test_a_producer_the_caller_named_is_kept(self, learnings: Any) -> None:
        with bind_execution_context(run_id="ambient"):
            await learnings.store(_learning(run_id="named", trigger_keys=["named"]))
        assert await learnings.produced_by("ambient", org_id="org-1") == []
        assert len(await learnings.produced_by("named", org_id="org-1")) == 1

    @pytest.mark.ac("SPEC-083026-b2b5/AC-5")
    async def test_a_blank_run_id_returns_nothing_rather_than_the_unattributed(
        self, learnings: Any
    ) -> None:
        """ "Which learnings did no execution produce" is a different question,
        and answering it here means a caller with an unresolved id silently gets
        the wrong set."""
        await learnings.store(_learning(trigger_keys=["orphan"]))
        assert await learnings.produced_by("", org_id="org-1") == []

    @pytest.mark.ac("SPEC-083026-b2b5/AC-5")
    async def test_provenance_does_not_cross_a_scope(self, learnings: Any) -> None:
        with bind_execution_context(run_id="r-1"):
            await learnings.store(_learning(org_id="org-1", trigger_keys=["scoped-a"]))
            await learnings.store(_learning(org_id="org-2", trigger_keys=["scoped-b"]))

        mine = await learnings.produced_by("r-1", org_id="org-1")
        assert [x.org_id for x in mine] == ["org-1"]

    @pytest.mark.ac("SPEC-083026-b2b5/AC-2")
    async def test_the_producer_survives_the_round_trip(self, learnings: Any) -> None:
        with bind_execution_context(run_id="r-2", node_run_id="nr-2", attempt_id="a-2"):
            await learnings.store(_learning(trigger_keys=["round-trip"]))

        [found] = await learnings.produced_by("r-2", org_id="org-1")
        assert found.learning == "check the branch first"
        assert found.node_run_id == "nr-2"
        assert found.attempt_id == "a-2"


# ─── Outcomes ─────────────────────────────────────────────────────────────────


@pytest.fixture(params=["sqlite", "postgres"])
async def outcomes(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """No in-memory case: `InMemoryOutcomeStore` keeps `Outcome` objects as
    given, so it can only ever agree with itself about what was persisted."""
    if request.param == "sqlite":
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore

        conn = await _sqlite_conn()
        store = SqliteOutcomeStore(conn)
        await store.ensure_schema()
        try:
            yield store, conn, "sqlite"
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_outcomes import PgOutcomeStore

    # No `ensure_schema`: `PgOutcomeStore` has none. Its table comes from the
    # migrations, which is why the DSN must point at a migrated database.
    yield PgOutcomeStore(pg_pool), pg_pool, "postgres"


async def _stored_provenance(handle: Any, kind: str, outcome_id: int) -> tuple[Any, Any, Any]:
    """Read the three columns straight out of the row, not through a mapper.

    A mapper that dropped them would agree with a write that dropped them; the
    row is what a later reader actually has.
    """
    if kind == "sqlite":
        # No `dag_run_id` here: the SQLite twin's table never had one, along
        # with seven other columns PostgreSQL carries. That divergence is real
        # and is not this change's to close, so the shared assertion asks each
        # backend only what it can answer.
        cursor = await handle.execute(
            "SELECT run_id, node_run_id, attempt_id FROM outcomes WHERE id = ?", (outcome_id,)
        )
        row = await cursor.fetchone()
        return (row[0], row[1], row[2], None)
    async with handle.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT run_id, node_run_id, attempt_id, dag_run_id FROM outcomes WHERE id = $1",
            outcome_id,
        )
    return (row["run_id"], row["node_run_id"], row["attempt_id"], row["dag_run_id"])


class TestAnOutcomeNamesItsProducer:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-3")
    async def test_the_canonical_ids_land_beside_the_dag_identity(self, outcomes: Any) -> None:
        """Not instead of it: `dag_run_id` names a real hive-conductor object
        the Conductor UI reads, and ADR-019 puts that on the product side."""
        store, handle, kind = outcomes
        with bind_execution_context(run_id="r-1", node_run_id="nr-1", attempt_id="a-1"):
            outcome_id = await store.record(
                Outcome(
                    request_id="req-1",
                    task_type="code",
                    success=True,
                    created_at=datetime.now(UTC),
                    dag_run_id="dag-run-1",
                )
            )

        run_id, node_run_id, attempt_id, dag_run_id = await _stored_provenance(
            handle, kind, outcome_id
        )
        assert (run_id, node_run_id, attempt_id) == ("r-1", "nr-1", "a-1")
        if kind == "postgres":
            assert dag_run_id == "dag-run-1"

    @pytest.mark.ac("SPEC-083026-b2b5/AC-4")
    async def test_an_outcome_outside_an_execution_stores_null_not_empty(
        self, outcomes: Any
    ) -> None:
        """An empty string reads as "produced by a Run whose id is empty",
        which is a claim. NULL reads as "no execution was in scope"."""
        store, handle, kind = outcomes
        outcome_id = await store.record(
            Outcome(request_id="req-2", task_type="code", created_at=datetime.now(UTC))
        )

        run_id, node_run_id, attempt_id, _ = await _stored_provenance(handle, kind, outcome_id)
        assert run_id is None
        assert node_run_id is None
        assert attempt_id is None


class TestTheOutcomeRoundTripCarriesTheProducer:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-3")
    async def test_a_recorded_outcome_reads_back_naming_its_run(self, pg_pool: Any) -> None:
        """PostgreSQL only: it is the store with a read path returning `Outcome`
        objects, so it is the only one where the mapper can drop a column the
        writer stored — the defect #696 found three times in one store.

        On the session's pool, not one of its own. A second pool's
        `ensure_schema` takes an ACCESS EXCLUSIVE lock that the session pool's
        open connection blocks, and the suite hangs rather than failing.
        """
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.persistence.pg_outcomes import PgOutcomeStore, _row_to_outcome

        store = PgOutcomeStore(pg_pool)
        with bind_execution_context(run_id="r-read", attempt_id="a-read"):
            await store.record(
                Outcome(
                    request_id="req-read",
                    task_type="round-trip-provenance",
                    success=True,
                    org_id="org-provenance",
                    created_at=datetime.now(UTC),
                )
            )
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM outcomes WHERE task_type = $1", "round-trip-provenance"
            )

        mapped = [_row_to_outcome(row) for row in rows]
        assert [(m.run_id, m.attempt_id) for m in mapped] == [("r-read", "a-read")]


# ─── A file created before the columns existed ────────────────────────────────


class TestAnOlderSqliteFileIsUpgradedInPlace:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-6")
    async def test_existing_rows_survive_the_upgrade(self, tmp_path: Any) -> None:
        """Recreating the table is the only alternative, and it loses the rows
        a real deployment already has."""
        from maistro.persistence.sqlite_learnings import SqliteLearningStore

        path = tmp_path / "old.db"
        conn = await aiosqlite.connect(path)
        await conn.execute(
            """CREATE TABLE learnings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   category TEXT NOT NULL DEFAULT 'general',
                   trigger_keys TEXT NOT NULL DEFAULT '[]',
                   learning TEXT NOT NULL DEFAULT '',
                   tool_name TEXT NOT NULL DEFAULT '',
                   agent_id TEXT NOT NULL DEFAULT '',
                   user_id TEXT,
                   org_id TEXT NOT NULL DEFAULT '',
                   scope TEXT NOT NULL DEFAULT 'agent',
                   hit_count INTEGER NOT NULL DEFAULT 0,
                   status TEXT NOT NULL DEFAULT 'active',
                   rca_category TEXT,
                   rca_prevention TEXT NOT NULL DEFAULT '',
                   success_after_use INTEGER NOT NULL DEFAULT 0,
                   failure_after_use INTEGER NOT NULL DEFAULT 0
               )"""
        )
        await conn.execute(
            "INSERT INTO learnings (learning, tool_name, org_id, trigger_keys) "
            "VALUES ('older wisdom', 'bash', 'org-1', '[\"old\"]')"
        )
        await conn.commit()

        store = SqliteLearningStore(conn)
        await store.ensure_schema()

        cursor = await conn.execute("PRAGMA table_info(learnings)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert {"run_id", "node_run_id", "attempt_id"} <= columns

        survivors = await store.find_relevant("old", org_id="org-1")
        assert [s.learning for s in survivors] == ["older wisdom"]
        assert survivors[0].run_id == ""

        with bind_execution_context(run_id="r-after"):
            await store.store(_learning(trigger_keys=["after"]))
        assert len(await store.produced_by("r-after", org_id="org-1")) == 1
        await conn.close()

    @pytest.mark.ac("SPEC-083026-b2b5/AC-6")
    async def test_an_older_outcomes_file_gains_the_columns_and_keeps_its_rows(
        self, tmp_path: Any
    ) -> None:
        """The outcomes twin's own in-place branch. Held separately from the
        learnings one because they are separate code paths, and a test of one
        says nothing about the other."""
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore

        conn = await aiosqlite.connect(tmp_path / "old-outcomes.db")
        await conn.execute(
            """CREATE TABLE outcomes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   request_id TEXT NOT NULL DEFAULT '',
                   task_type TEXT NOT NULL DEFAULT '',
                   model_used TEXT NOT NULL DEFAULT '',
                   provider TEXT NOT NULL DEFAULT '',
                   tool_calls TEXT NOT NULL DEFAULT '',
                   success INTEGER NOT NULL DEFAULT 1,
                   error_type TEXT NOT NULL DEFAULT '',
                   response_time_ms INTEGER NOT NULL DEFAULT 0,
                   team_id TEXT NOT NULL DEFAULT '',
                   user_id TEXT NOT NULL DEFAULT '',
                   agent_id TEXT NOT NULL DEFAULT '',
                   input_tokens INTEGER NOT NULL DEFAULT 0,
                   output_tokens INTEGER NOT NULL DEFAULT 0,
                   charged_microchips INTEGER NOT NULL DEFAULT 0,
                   pricing_version TEXT NOT NULL DEFAULT '',
                   created_at TEXT NOT NULL
               )"""
        )
        await conn.execute(
            "INSERT INTO outcomes (request_id, created_at) VALUES ('older', '2026-01-01T00:00:00')"
        )
        await conn.commit()

        store = SqliteOutcomeStore(conn)
        await store.ensure_schema()

        cursor = await conn.execute("PRAGMA table_info(outcomes)")
        columns = {row[1] for row in await cursor.fetchall()}
        assert {"run_id", "node_run_id", "attempt_id"} <= columns

        cursor = await conn.execute("SELECT request_id, run_id FROM outcomes")
        assert await cursor.fetchall() == [("older", None)]

        with bind_execution_context(run_id="r-after"):
            await store.record(Outcome(request_id="newer", created_at=datetime.now(UTC)))
        cursor = await conn.execute("SELECT run_id FROM outcomes WHERE request_id = 'newer'")
        assert await cursor.fetchone() == ("r-after",)
        await conn.close()


class _Embeddings:
    """The narrowest embedding client `DurableHybridLearningStore` will accept.

    Its constructor checks the width at wiring time, so a double is required
    even for a test that never embeds anything.
    """

    from maistro.memory.vectors import EMBEDDING_DIMENSIONS as _WIDTH

    dimension = _WIDTH

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self._WIDTH

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._WIDTH for _ in texts]


class TestTheWrappingStoresDelegateProvenance:
    """`HybridLearningStore` and `DurableHybridLearningStore` wrap another store.

    They are what the container actually builds when embeddings are configured,
    so a delegation that silently returned nothing would make `produced_by`
    answer "no learnings" on the deployments that have the most.
    """

    async def test_the_embedding_wrapper_asks_the_store_it_wraps(self) -> None:
        from maistro.memory.learnings.embeddings import HybridLearningStore
        from maistro.memory.learnings.store import InMemoryLearningStore

        inner = InMemoryLearningStore()
        wrapper = HybridLearningStore(inner)
        with bind_execution_context(run_id="r-wrapped"):
            await wrapper.store(_learning(trigger_keys=["wrapped"]))

        found = await wrapper.produced_by("r-wrapped", org_id="org-1")
        assert [x.learning for x in found] == ["check the branch first"]

    async def test_the_durable_wrapper_asks_the_store_it_wraps(self) -> None:
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore
        from maistro.memory.learnings.store import InMemoryLearningStore

        inner = InMemoryLearningStore()
        wrapper = DurableHybridLearningStore(inner, _Embeddings())  # type: ignore[arg-type]
        with bind_execution_context(run_id="r-durable"):
            await wrapper.store(_learning(trigger_keys=["durable"]))

        found = await wrapper.produced_by("r-durable", org_id="org-1")
        assert [x.learning for x in found] == ["check the branch first"]


class TestTheVolatileBackendFillsItToo:
    """`memory://` selects these, so a gap here is a gap nothing else catches.

    Both SQL twins resolve the ambient provenance. A volatile store that did
    not would let every behavioural test pass while only the durable ones did
    the work — and `memory://` is the default in dev and test (Codex, #709).
    """

    @pytest.mark.ac("SPEC-083026-b2b5/AC-1")
    async def test_an_in_memory_outcome_names_the_execution_that_recorded_it(self) -> None:
        from maistro.memory.outcomes import InMemoryOutcomeStore

        store = InMemoryOutcomeStore()
        outcome = Outcome(request_id="r", org_id="org-a")
        with bind_execution_context(run_id="run-1", node_run_id="nr-1", attempt_id="a-1"):
            await store.record(outcome)

        assert (outcome.run_id, outcome.node_run_id, outcome.attempt_id) == (
            "run-1",
            "nr-1",
            "a-1",
        )

    async def test_an_in_memory_outcome_recorded_outside_an_execution_names_none(self) -> None:
        from maistro.memory.outcomes import InMemoryOutcomeStore

        outcome = Outcome(request_id="r", org_id="org-a")
        await InMemoryOutcomeStore().record(outcome)

        assert (outcome.run_id, outcome.node_run_id, outcome.attempt_id) == ("", "", "")

    async def test_a_producer_the_caller_named_is_kept(self) -> None:
        from maistro.memory.outcomes import InMemoryOutcomeStore

        outcome = Outcome(request_id="r", org_id="org-a", run_id="named")
        with bind_execution_context(run_id="ambient"):
            await InMemoryOutcomeStore().record(outcome)

        assert outcome.run_id == "named"


class TestDedupMovesTheProducerWithTheContent:
    @pytest.mark.ac("SPEC-083026-b2b5/AC-1")
    async def test_the_run_that_supplied_the_surviving_text_is_the_one_recorded(self) -> None:
        """Dedup replaces the learning text and its trigger keys. Leaving the
        earlier Run's ids on the row would attribute the surviving content to a
        Run that no longer wrote it (Codex, #709)."""
        from maistro.memory.learnings.store import InMemoryLearningStore

        store = InMemoryLearningStore()
        with bind_execution_context(run_id="run-first", attempt_id="attempt-first"):
            first_id = await store.store(
                Learning(tool_name="deploy", trigger_keys=["a", "b"], learning="first")
            )
        with bind_execution_context(run_id="run-second", attempt_id="attempt-second"):
            second_id = await store.store(
                Learning(tool_name="deploy", trigger_keys=["a", "b"], learning="second")
            )

        assert second_id == first_id, "the second store must have deduped onto the first"
        [kept] = await store.find_relevant("a")
        assert kept.learning == "second"
        assert kept.run_id == "run-second"
        assert kept.attempt_id == "attempt-second"

    async def test_the_deduped_learning_is_found_under_the_run_that_wrote_it(self) -> None:
        from maistro.memory.learnings.store import InMemoryLearningStore

        store = InMemoryLearningStore()
        with bind_execution_context(run_id="run-first"):
            await store.store(
                Learning(tool_name="deploy", trigger_keys=["a", "b"], learning="first")
            )
        with bind_execution_context(run_id="run-second"):
            await store.store(
                Learning(tool_name="deploy", trigger_keys=["a", "b"], learning="second")
            )

        assert [item.learning for item in await store.produced_by("run-second")] == ["second"]
        assert await store.produced_by("run-first") == []
