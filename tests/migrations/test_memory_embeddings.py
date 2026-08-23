"""The embedding is on the row, so scope and similarity resolve in one query (#188).

`ADR-082226-5104` chose pgvector; migration 001 gave a column to
`memory_entries` alone. The tables `maistro.memory` actually uses had none, so
a similarity read meant fetching candidates and filtering by scope in Python.

**Why the scope test is written the way it is.** Asserting that
`find_similar` returns only in-scope rows would pass over the exact bug worth
preventing: a Python-side filter applied after an unscoped fetch returns the
same list. So the case asserts the *plan* — that PostgreSQL's own filter names
the scope column — as well as the rows. A ranking-only test would have been
green on the design this issue exists to reject.

Skips without `MAISTRO_TEST_DATABASE_URL`; `MAISTRO_REQUIRE_PG_LEGS` turns the
skip into a failure where a server is guaranteed.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from maistro.memory.vectors import (
    EMBEDDING_DIMENSIONS,
    require_matching_dimension,
    to_pgvector_literal,
)
from maistro.persistence.pg_learnings import similarity_query
from maistro.types.errors import ConfigError
from maistro.types.memory import Learning

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")
SCRATCH_DB = "maistro_embedding_test"

#: Only `learnings` gets a column in this change. `outcomes` and
#: `episodic_memories` land theirs with the producers that write them --
#: an index over a column nothing populates is the no-caller shape #188 rejects.
_EMBEDDED_TABLES = ("learnings",)


# --------------------------------------------------------------------------
# The parts that need no server
# --------------------------------------------------------------------------


class TestTheDeclaredWidth:
    def test_the_constant_matches_what_the_migration_creates(self) -> None:
        """A constant that drifted from the DDL would be a check that passes
        while every write fails."""
        migration = (
            REPO_ROOT / "alembic" / "versions" / "007_memory_embedding_columns.py"
        ).read_text(encoding="utf-8")

        assert f"_DIMENSIONS = {EMBEDDING_DIMENSIONS}" in migration

    def test_a_client_at_another_width_is_refused(self) -> None:
        class Narrow:
            dimension = 384

            async def embed(self, text: str) -> list[float]:  # pragma: no cover - unused
                return []

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return []  # pragma: no cover - unused

        with pytest.raises(ConfigError) as excinfo:
            require_matching_dimension(Narrow())

        message = str(excinfo.value)
        assert "384" in message and str(EMBEDDING_DIMENSIONS) in message, (
            "an operator needs both numbers to know which end to change"
        )

    def test_a_client_at_the_declared_width_passes(self) -> None:
        class Matching:
            dimension = EMBEDDING_DIMENSIONS

            async def embed(self, text: str) -> list[float]:  # pragma: no cover - unused
                return []

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return []  # pragma: no cover - unused

        require_matching_dimension(Matching())

    def test_the_literal_is_what_pgvector_parses(self) -> None:
        """`str(list)` happens to work because Python's repr and pgvector's
        input format agree on brackets and commas. That coincidence is not a
        contract, and integers must still cross as floats."""
        assert to_pgvector_literal([1, -0.5, 2.0]) == "[1.0,-0.5,2.0]"


# --------------------------------------------------------------------------
# The parts that need a real server
# --------------------------------------------------------------------------


def _require_postgres() -> str:
    if not DATABASE_URL:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise AssertionError(
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is not"
            )
        pytest.skip("MAISTRO_TEST_DATABASE_URL is not set")
    return DATABASE_URL


def _alembic_env(url: str) -> dict[str, str]:
    """`DB_*` for alembic's `DatabaseSettings`, pointed at the scratch database.

    Not `DATABASE_URL`: on this branch `alembic/env.py` builds its URL from
    `DatabaseSettings`, whose `env_prefix` is `DB_`, so a `DATABASE_URL` is
    ignored and the run silently goes to `localhost:5432`. #187 makes one
    resolver serve both; until that lands the sibling suites here spell it the
    same way, and so does this one.
    """
    parts = urlsplit(url)
    return {
        **os.environ,
        "DB_HOST": parts.hostname or "127.0.0.1",
        "DB_PORT": str(parts.port or 5432),
        "DB_NAME": SCRATCH_DB,
        "DB_USER": parts.username or "postgres",
        "DB_PASSWORD": parts.password or "",
    }


async def _recreate_scratch_database(url: str) -> None:
    import asyncpg

    admin = await asyncpg.connect(urlsplit(url)._replace(path="/postgres").geturl())
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await admin.close()


@pytest.fixture(scope="module")
def migrated_url() -> str:
    """A scratch database with the whole chain applied, from empty.

    The full `upgrade head`: 007 alters tables 001 creates, so the chain has to
    run end to end — which also means the `vector` extension, and so the
    `pgvector/pgvector:pg17` image rather than plain `postgres:17`.
    """
    url = _require_postgres()
    asyncio.run(_recreate_scratch_database(url))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=_alembic_env(url),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"alembic upgrade head failed with exit {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        raise AssertionError(msg)
    return urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl()


@pytest.fixture
async def store(migrated_url):
    """A `PgLearningStore` on a pool of its own, emptied between tests."""
    import asyncpg

    from maistro.persistence.pg_learnings import PgLearningStore

    pool = await asyncpg.create_pool(migrated_url, min_size=1, max_size=2)
    assert pool is not None
    try:
        await pool.execute("TRUNCATE learnings")
        yield PgLearningStore(pool)
    finally:
        await pool.close()


def _vector(seed: float) -> list[float]:
    """A unit-ish vector that leans on one axis, so ordering is predictable."""
    vec = [0.001] * EMBEDDING_DIMENSIONS
    vec[0] = seed
    return vec


def _learning(text: str, *, org_id: str, agent_id: str = "") -> Learning:
    """A learning distinct enough not to be deduplicated into another one.

    `PgLearningStore.store` merges on `tool_name` + trigger-key overlap within
    an org, so a fixture that gave every row the same tool and keys silently
    collapsed a three-row corpus into one — and the similarity assertions then
    failed for a reason that had nothing to do with similarity.
    """
    return Learning(
        category="general",
        trigger_keys=[text],
        learning=text,
        tool_name=f"tool-{text}",
        source_query="q",
        org_id=org_id,
        agent_id=agent_id,
    )


class TestTheColumnExists:
    async def test_every_memory_table_gained_a_vector_of_the_declared_width(
        self, migrated_url
    ) -> None:
        import asyncpg

        conn = await asyncpg.connect(migrated_url)
        try:
            for table in _EMBEDDED_TABLES:
                row = await conn.fetchrow(
                    """SELECT a.atttypmod AS dimensions
                       FROM pg_attribute a
                       JOIN pg_class c ON c.oid = a.attrelid
                       WHERE c.relname = $1 AND a.attname = 'embedding'""",
                    table,
                )
                assert row is not None, f"{table} has no embedding column"
                assert row["dimensions"] == EMBEDDING_DIMENSIONS, (
                    f"{table}.embedding is vector({row['dimensions']})"
                )
        finally:
            await conn.close()

    async def test_the_index_is_hnsw_over_cosine(self, migrated_url) -> None:
        """An index built for a different distance function is silently unused
        by a cosine-ordered query: the read still works, and still scans."""
        import asyncpg

        conn = await asyncpg.connect(migrated_url)
        try:
            for table in _EMBEDDED_TABLES:
                definition = await conn.fetchval(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = $1",
                    f"ix_{table}_embedding_hnsw",
                )
                assert definition is not None, f"{table} has no embedding index"
                assert "hnsw" in definition
                assert "vector_cosine_ops" in definition
        finally:
            await conn.close()


class TestSimilarityAndScopeResolveTogether:
    async def test_the_nearest_vector_ranks_first(self, store) -> None:
        far = await store.store(_learning("far", org_id="org-1"))
        near = await store.store(_learning("near", org_id="org-1"))
        await store.set_embedding(far, _vector(0.01))
        await store.set_embedding(near, _vector(9.0))

        found = await store.find_similar(_vector(9.0), org_id="org-1")

        assert next(lr.learning for lr in found) == "near"

    async def test_another_orgs_row_is_not_returned(self, store) -> None:
        mine = await store.store(_learning("mine", org_id="org-1"))
        theirs = await store.store(_learning("theirs", org_id="org-2"))
        await store.set_embedding(mine, _vector(0.01))
        # Deliberately the *better* match, so a missing filter is visible in the
        # ranking rather than hidden behind one.
        await store.set_embedding(theirs, _vector(9.0))

        found = await store.find_similar(_vector(9.0), org_id="org-1")

        assert [lr.learning for lr in found] == ["mine"]

    async def test_the_database_applies_the_scope_filter(self, store) -> None:
        """The property this issue is actually about. A Python-side filter over
        an unscoped fetch returns the same rows as the test above, so only the
        plan distinguishes them -- and the plan has to be of the query that
        really runs, which is why `similarity_query` is a function rather than
        a string inside the method."""
        rows = await store._pool.fetch(
            f"EXPLAIN {similarity_query(scoped_to_agent=False)}",
            to_pgvector_literal(_vector(1.0)),
            "org-1",
            10,
        )
        plan = "\n".join(row[0] for row in rows)

        assert "org_id" in plan, f"the scope column is not in the plan:\n{plan}"
        assert "Filter" in plan or "Index Cond" in plan, (
            f"the scope predicate is not being applied by PostgreSQL:\n{plan}"
        )

    async def test_a_row_with_no_embedding_is_excluded(self, store) -> None:
        """pgvector sorts NULLs last rather than excluding them, so without the
        predicate an unembedded corpus returns arbitrary rows that look
        ranked."""
        await store.store(_learning("never embedded", org_id="org-1"))
        embedded = await store.store(_learning("embedded", org_id="org-1"))
        await store.set_embedding(embedded, _vector(1.0))

        found = await store.find_similar(_vector(1.0), org_id="org-1")

        assert [lr.learning for lr in found] == ["embedded"]

    async def test_an_agent_scoped_read_still_sees_shared_rows(self, store) -> None:
        shared = await store.store(_learning("shared", org_id="org-1", agent_id=""))
        mine = await store.store(_learning("mine", org_id="org-1", agent_id="agent-a"))
        other = await store.store(_learning("other", org_id="org-1", agent_id="agent-b"))
        for learning_id in (shared, mine, other):
            await store.set_embedding(learning_id, _vector(1.0))

        found = await store.find_similar(_vector(1.0), org_id="org-1", agent_id="agent-a")

        assert sorted(lr.learning for lr in found) == ["mine", "shared"]

    async def test_the_embedding_survives_the_pool(self, store) -> None:
        """The point of the column over `HybridLearningStore`'s process-local
        dict: a vector written once is still there for a reader that never saw
        the write."""
        learning_id = await store.store(_learning("durable", org_id="org-1"))
        await store.set_embedding(learning_id, _vector(3.0))

        stored = await store._pool.fetchval(
            "SELECT embedding IS NOT NULL FROM learnings WHERE id = $1", learning_id
        )

        assert stored is True


class TestAWrongWidthIsRefusedBeforeTheDatabaseSeesIt:
    async def test_writing_a_short_vector_names_both_widths(self, store) -> None:
        learning_id = await store.store(_learning("x", org_id="org-1"))

        with pytest.raises(ValueError, match=str(EMBEDDING_DIMENSIONS)):
            await store.set_embedding(learning_id, [0.1, 0.2])

    async def test_querying_with_a_short_vector_names_both_widths(self, store) -> None:
        with pytest.raises(ValueError, match=str(EMBEDDING_DIMENSIONS)):
            await store.find_similar([0.1, 0.2], org_id="org-1")


class TestTheVectorsHaveAProducerAndAConsumer:
    """The acceptance criterion that stops this becoming a column only writes
    accumulate in: `set_embedding` and `find_similar` have a real caller, and
    that caller writes on store and reads on search."""

    @staticmethod
    def _client():
        class Client:
            dimension = EMBEDDING_DIMENSIONS

            async def embed(self, text: str) -> list[float]:
                # Leans on one axis by text length, so ordering is predictable
                # without depending on a model.
                return _vector(float(len(text)))

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed(t) for t in texts]

        return Client()

    async def test_storing_a_learning_persists_its_vector(self, store) -> None:
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        hybrid = DurableHybridLearningStore(store, self._client())
        learning_id = await hybrid.store(_learning("durable", org_id="org-1"))

        embedded = await store._pool.fetchval(
            "SELECT embedding IS NOT NULL FROM learnings WHERE id = $1", learning_id
        )

        assert embedded is True, "the write path did not reach the column"

    async def test_a_search_ranks_by_the_stored_vector(self, store) -> None:
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        hybrid = DurableHybridLearningStore(store, self._client())
        await hybrid.store(_learning("aaaaaaaaaaaaaaaaaaaa", org_id="org-1"))
        await hybrid.store(_learning("bb", org_id="org-1"))

        found = await hybrid.find_relevant("cc", org_id="org-1")

        assert next(lr.learning for lr in found) == "bb", (
            "the nearest stored vector did not rank first"
        )

    async def test_an_unembedded_corpus_falls_back_to_keyword_search(self, store) -> None:
        """A corpus written before the column existed has no vectors, so a
        similarity-only read would report it as empty rather than un-embedded."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        await store.store(_learning("legacy", org_id="org-1"))
        hybrid = DurableHybridLearningStore(store, self._client())

        found = await hybrid.find_relevant("legacy", org_id="org-1")

        assert [lr.learning for lr in found] == ["legacy"]

    async def test_a_mismatched_client_is_refused_at_wiring_time(self, store) -> None:
        """Not at the first write: a configuration error discovered inside a
        background path puts the message a long way from its cause."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        class Narrow:
            dimension = 384

            async def embed(self, text: str) -> list[float]:  # pragma: no cover - unused
                return []

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return []  # pragma: no cover - unused

        with pytest.raises(ConfigError):
            DurableHybridLearningStore(store, Narrow())

    async def test_an_embedding_failure_does_not_lose_the_learning(self, store) -> None:
        """The row is already committed by then; losing it because the vector
        could not be computed would trade degraded search for no memory."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        class Failing:
            dimension = EMBEDDING_DIMENSIONS

            async def embed(self, text: str) -> list[float]:
                raise RuntimeError("model unavailable")

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                raise RuntimeError("model unavailable")  # pragma: no cover - unused

        hybrid = DurableHybridLearningStore(store, Failing())
        learning_id = await hybrid.store(_learning("kept", org_id="org-1"))

        assert learning_id > 0
        found = await hybrid.find_relevant("kept", org_id="org-1")
        assert [lr.learning for lr in found] == ["kept"], "keyword search must still find it"


class TestTheReviewFindings:
    """Six ways the first version was wrong, each pinned by the case that
    would have caught it."""

    @staticmethod
    def _client():
        class Client:
            dimension = EMBEDDING_DIMENSIONS

            async def embed(self, text: str) -> list[float]:
                return _vector(float(len(text)))

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed(t) for t in texts]

        return Client()

    async def test_a_deduplicated_row_keeps_a_vector_of_its_own_text(self, store) -> None:
        """`store` deduplicates by trigger-key overlap and returns the *existing*
        row's id without replacing its text. Embedding the submitted text then
        stamped the surviving row with a vector describing content it does not
        hold, so every later ranking was about text no caller can see."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        hybrid = DurableHybridLearningStore(store, self._client())
        first = await hybrid.store(_learning("original", org_id="org-1"))

        duplicate = Learning(
            category="general",
            trigger_keys=["original"],
            learning="a completely different and much much longer sentence",
            tool_name="tool-original",
            source_query="q",
            org_id="org-1",
        )
        second = await hybrid.store(duplicate)

        assert second == first, "the fixture must actually exercise the dedup path"
        persisted = await store.text_of(first)
        expected = await self._client().embed(persisted)
        stored = await store._pool.fetchval(
            "SELECT embedding = $1::vector FROM learnings WHERE id = $2",
            to_pgvector_literal(expected),
            first,
        )
        assert stored is True, "the row's vector describes text the row does not contain"

    async def test_a_legacy_row_stays_reachable_beside_an_embedded_one(self, store) -> None:
        """The P1. One embedded row in scope used to hide every unembedded row
        for good -- including a query that matched a legacy row exactly."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        await store.store(_learning("legacy", org_id="org-1"))
        hybrid = DurableHybridLearningStore(store, self._client())
        await hybrid.store(_learning("embedded", org_id="org-1"))

        found = await hybrid.find_relevant("legacy", org_id="org-1")

        assert "legacy" in [lr.learning for lr in found]

    async def test_a_row_whose_embedding_failed_stays_reachable(self, store) -> None:
        """The docstring promises it stays keyword-searchable; before the merge
        it was reachable only while no other row in scope had a vector."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        class SometimesFailing:
            dimension = EMBEDDING_DIMENSIONS

            def __init__(self) -> None:
                self.fail_for = "unembeddable"

            async def embed(self, text: str) -> list[float]:
                if self.fail_for in text:
                    raise RuntimeError("model unavailable")
                return _vector(float(len(text)))

            async def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [await self.embed(t) for t in texts]  # pragma: no cover - unused

        hybrid = DurableHybridLearningStore(store, SometimesFailing())
        await hybrid.store(_learning("unembeddable", org_id="org-1"))
        await hybrid.store(_learning("fine", org_id="org-1"))

        found = await hybrid.find_relevant("unembeddable", org_id="org-1")

        assert "unembeddable" in [lr.learning for lr in found]

    async def test_merged_results_do_not_repeat_a_row(self, store) -> None:
        """Similarity and keyword search overlap; a row in both must appear
        once, or `max_results` silently returns fewer distinct learnings."""
        from maistro.memory.learnings.durable_hybrid import DurableHybridLearningStore

        hybrid = DurableHybridLearningStore(store, self._client())
        await hybrid.store(_learning("shared", org_id="org-1"))

        found = await hybrid.find_relevant("shared", org_id="org-1")

        ids = [lr.id for lr in found]
        assert len(ids) == len(set(ids))

    async def test_the_similarity_read_enables_filtered_recall(self) -> None:
        """HNSW applies the scope predicate *after* its approximate scan, so
        without iterative scan a large multi-org table can return nothing while
        matching in-scope vectors exist.

        Asserted by recording what the connection was actually asked to run.
        The first version of this test set the GUC itself in a transaction of
        its own and read it back, which is true of any database and says
        nothing about `find_similar` -- it stayed green when the setting was
        turned off, which is how it was caught.
        """
        from maistro.persistence.pg_learnings import _ITERATIVE_SCAN, PgLearningStore

        executed: list[str] = []

        class FakeConn:
            async def execute(self, statement: str, *args: object) -> None:
                executed.append(statement)

            async def fetch(self, statement: str, *args: object) -> list[object]:
                executed.append(statement)
                return []

            def transaction(self):
                return _NullContext()

        class _NullContext:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: object) -> None:
                return None

        class FakePool:
            def acquire(self):
                return _ConnContext()

        class _ConnContext:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()

            async def __aexit__(self, *exc: object) -> None:
                return None

        store = PgLearningStore(FakePool())  # type: ignore[arg-type]
        await store.find_similar(_vector(1.0), org_id="org-1")

        assert any("hnsw.iterative_scan" in statement for statement in executed), (
            f"the similarity read did not configure filtered recall: {executed}"
        )
        assert _ITERATIVE_SCAN != "off", "iterative scan disabled is the bug, not the fix"


class TestOnlyTheTableWithAProducerGetsAColumn:
    async def test_outcomes_and_episodic_are_left_alone(self, migrated_url) -> None:
        """`PgOutcomeStore` never reads the column and the container wires
        `InMemoryEpisodicStore` even on PostgreSQL, so a column and index on
        either would exist, cost write time, and index nothing -- the
        no-caller shape #188 asks this change not to create."""
        import asyncpg

        conn = await asyncpg.connect(migrated_url)
        try:
            for table in ("outcomes", "episodic_memories"):
                present = await conn.fetchval(
                    """SELECT count(*) FROM pg_attribute a
                       JOIN pg_class c ON c.oid = a.attrelid
                       WHERE c.relname = $1 AND a.attname = 'embedding'""",
                    table,
                )
                assert present == 0, (
                    f"{table} has an embedding column but nothing writes or reads it"
                )
        finally:
            await conn.close()
