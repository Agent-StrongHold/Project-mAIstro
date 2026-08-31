"""`memory_entries.embedding` is a vector, and the test asks its type (#188).

The defect these exist for is not that a column was missing. It is that a
column named `embedding` has existed since migration 001 while being `text`,
and every check that could have noticed asked whether it exists rather than
what it is. So the assertions here read `pg_catalog` and would fail on the
state `develop` shipped:

    learnings.embedding       => vector(1536)
    memory_entries.embedding  => text

`001` creates the column as `sa.Text` and then guards the vector `ALTER` with
`IF NOT EXISTS`, which PostgreSQL skips without error because a column of that
name is already there.

These need a real pgvector server; the type is the thing under test, so a
double would prove nothing. They skip without `MAISTRO_TEST_DATABASE_URL`,
and `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure where a server is
guaranteed.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from maistro.memory.vectors import EMBEDDING_DIMENSIONS

pytestmark = [pytest.mark.contract("boundary")]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The environment variables that name a usable PostgreSQL, in the order a
#: reader should trust them.
#:
#: Three rather than one, because the jobs that must run these tests do not
#: agree on a name. `quality.yml`'s Quality gate -- the job whose AC-state
#: ratchet decides whether a criterion counts as proven -- exports
#: `MAISTRO_TEST_PG_DSN` and `DATABASE_URL` and never sets
#: `MAISTRO_TEST_DATABASE_URL`. A suite reading only the last of those skips
#: there, and `ac_outcome_plugin` counts a skip as not-passing, so criteria
#: whose evidence needs a server become unprovable in the one job that asks
#: (#188; the same trap #328's comment in that workflow describes).
_DSN_VARIABLES = ("MAISTRO_TEST_DATABASE_URL", "MAISTRO_TEST_PG_DSN", "DATABASE_URL")


def _configured_dsn() -> str:
    for name in _DSN_VARIABLES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


DATABASE_URL = _configured_dsn()
SCRATCH_DB = "maistro_embedding_type_test"

#: The revision immediately before the repair -- the state every deployment has
#: been in. Tests that start here are testing the upgrade an operator will
#: actually run, not a fresh database that never had the defect.
BROKEN_REVISION = "028"

_TYPE_QUERY = """
    SELECT format_type(a.atttypid, a.atttypmod)
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
     WHERE c.relname = $1 AND a.attname = $2 AND a.attnum > 0
"""


def _require_postgres() -> str:
    if not DATABASE_URL:
        named = ", ".join(_DSN_VARIABLES)
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise AssertionError(f"MAISTRO_REQUIRE_PG_LEGS is set but none of {named} is")
        pytest.skip(f"set one of {named} to a PostgreSQL with pgvector to run these")
    return DATABASE_URL


def _alembic_env(url: str) -> dict[str, str]:
    """Every variable alembic might resolve its URL from, all naming the scratch database.

    Both spellings, deliberately. `DB_*` feeds `DatabaseSettings` (`env_prefix`
    `DB_`), and since #187 gave alembic and the container one resolver, a
    `DATABASE_URL` in the environment can win instead. The Quality gate exports
    `DATABASE_URL` pointing at *its* database, so setting only `DB_*` here sent
    `alembic upgrade` to the CI database rather than the scratch one: the
    upgrade succeeded, exited 0, and left this suite's scratch database empty.
    The guard in `_seed_broken_rows` is what caught it (#188).

    Overriding rather than unsetting: a resolver that falls back to a default
    when the variable is absent would find `localhost:5432` and be wrong in a
    quieter way.
    """
    parts = urlsplit(url)
    scratch = urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl()
    return {
        **os.environ,
        "DB_HOST": parts.hostname or "127.0.0.1",
        "DB_PORT": str(parts.port or 5432),
        "DB_NAME": SCRATCH_DB,
        "DB_USER": parts.username or "postgres",
        "DB_PASSWORD": parts.password or "",
        "DATABASE_URL": scratch,
        "MAISTRO_DATABASE_URL": scratch,
    }


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=_alembic_env(url),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"alembic {' '.join(args)} failed with exit {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        raise AssertionError(msg)


async def _recreate_scratch_database(url: str) -> None:
    import asyncpg

    admin = await asyncpg.connect(urlsplit(url)._replace(path="/postgres").geturl())
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await admin.close()


def _literal(value: float, width: int = EMBEDDING_DIMENSIONS) -> str:
    return "[" + ",".join([str(value)] * width) + "]"


@pytest.fixture(scope="module")
def repaired_url() -> str:
    """A scratch database taken to the broken revision, seeded, then repaired.

    Deliberately not a fresh `upgrade head`. A database that never held a text
    value cannot show that the repair preserves one, and every real deployment
    arrives at `029` from `028` rather than from empty.
    """
    url = _require_postgres()
    asyncio.run(_recreate_scratch_database(url))
    scratch = urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl()

    _alembic(url, "upgrade", BROKEN_REVISION)
    asyncio.run(_seed_broken_rows(scratch))
    _alembic(url, "upgrade", "head")
    return scratch


async def _seed_broken_rows(scratch: str) -> None:
    """Four rows spanning what a `text` column can be left holding."""
    import asyncpg

    conn = await asyncpg.connect(scratch)
    try:
        held = await conn.fetchval(_TYPE_QUERY, "memory_entries", "embedding")
        assert held == "text", (
            f"expected the pre-repair column to be text, found {held!r} -- if this "
            f"fails the defect has been fixed somewhere else and this suite is stale"
        )
        for content, embedding in (
            ("null embedding", None),
            ("well formed at the declared width", _literal(0.5)),
            ("well formed at the wrong width", "[1,2,3]"),
            ("not a vector at all", "banana"),
        ):
            await conn.execute(
                "INSERT INTO memory_entries (workspace, layer, content, embedding) "
                "VALUES ($1, $2, $3, $4)",
                "ws-1",
                "layer",
                content,
                embedding,
            )
    finally:
        await conn.close()


@pytest.fixture
async def conn(repaired_url):
    import asyncpg

    connection = await asyncpg.connect(repaired_url)
    try:
        yield connection
    finally:
        await connection.close()


class TestTheColumnIsAVector:
    @pytest.mark.ac("SPEC-083026-4b70/AC-1")
    async def test_the_catalog_reports_a_vector_at_the_declared_width(self, conn) -> None:
        """The whole defect in one assertion. Before `029` this read `text`."""
        held = await conn.fetchval(_TYPE_QUERY, "memory_entries", "embedding")

        assert held == f"vector({EMBEDDING_DIMENSIONS})"

    @pytest.mark.ac("SPEC-083026-4b70/AC-1")
    async def test_asking_only_whether_the_column_exists_would_not_have_caught_it(
        self, conn
    ) -> None:
        """Kept as a named case rather than a comment: the presence check is
        what every earlier check did, and it was green throughout."""
        present = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'memory_entries' AND column_name = 'embedding')"
        )

        assert present is True

    @pytest.mark.ac("SPEC-083026-4b70/AC-1")
    async def test_the_sibling_column_still_matches(self, conn) -> None:
        """`learnings` was always right, and must stay right: one width in one
        database is what ADR-082326-8194 chose."""
        held = await conn.fetchval(_TYPE_QUERY, "learnings", "embedding")

        assert held == f"vector({EMBEDDING_DIMENSIONS})"


class TestTheUpgradeKeepsWhatItCannotConvert:
    @pytest.mark.ac("SPEC-083026-4b70/AC-2")
    async def test_the_upgrade_completed_over_unconvertible_rows(self, conn) -> None:
        """The fixture would have raised had `alembic upgrade head` failed, so
        reaching here is the assertion. Named so a failure reads as "the
        upgrade aborted", which is the outcome being ruled out."""
        assert await conn.fetchval("SELECT count(*) FROM memory_entries") == 4

    @pytest.mark.ac("SPEC-083026-4b70/AC-2")
    async def test_a_malformed_value_is_readable_under_a_name_that_says_so(self, conn) -> None:
        row = await conn.fetchrow(
            "SELECT embedding, embedding_unconvertible FROM memory_entries "
            "WHERE content = 'not a vector at all'"
        )

        assert row["embedding"] is None
        assert row["embedding_unconvertible"] == "banana"

    @pytest.mark.ac("SPEC-083026-4b70/AC-2")
    async def test_a_wrong_width_vector_is_quarantined_rather_than_widened(self, conn) -> None:
        """The failure mode a plain `USING embedding::vector` would have hidden:
        `[1,2,3]` is valid input to `vector`, just not to `vector(1536)`. Padding
        it would produce a row that ranks plausibly and means nothing."""
        row = await conn.fetchrow(
            "SELECT embedding, embedding_unconvertible FROM memory_entries "
            "WHERE content = 'well formed at the wrong width'"
        )

        assert row["embedding"] is None
        assert row["embedding_unconvertible"] == "[1,2,3]"

    @pytest.mark.ac("SPEC-083026-4b70/AC-2")
    async def test_a_row_that_held_nothing_still_holds_nothing(self, conn) -> None:
        row = await conn.fetchrow(
            "SELECT embedding, embedding_unconvertible FROM memory_entries "
            "WHERE content = 'null embedding'"
        )

        assert row["embedding"] is None
        assert row["embedding_unconvertible"] is None

    @pytest.mark.ac("SPEC-083026-4b70/AC-3")
    async def test_a_convertible_value_survives_unchanged(self, conn) -> None:
        row = await conn.fetchrow(
            "SELECT embedding::text AS embedding, embedding_unconvertible FROM memory_entries "
            "WHERE content = 'well formed at the declared width'"
        )

        assert row["embedding_unconvertible"] is None
        assert row["embedding"] == _literal(0.5)


class TestSimilarityAndScopeResolveTogether:
    @pytest.mark.ac("SPEC-083026-4b70/AC-4")
    async def test_the_nearest_row_in_a_workspace_comes_back(self, conn) -> None:
        query = _literal(0.5)
        rows = await conn.fetch(
            "SELECT content FROM memory_entries "
            "WHERE workspace = $1 AND embedding IS NOT NULL "
            "ORDER BY embedding <=> $2::vector LIMIT 5",
            "ws-1",
            query,
        )

        assert [row["content"] for row in rows] == ["well formed at the declared width"]

    @pytest.mark.ac("SPEC-083026-4b70/AC-4")
    async def test_the_scope_predicate_is_the_databases_own(self, conn) -> None:
        """Asserting only that in-scope rows came back would pass over the bug
        worth preventing: a Python-side filter after an unscoped fetch returns
        the same list. So this reads the plan, the way the sibling suite for
        `learnings` does."""
        plan = "\n".join(
            record["QUERY PLAN"]
            for record in await conn.fetch(
                "EXPLAIN SELECT content FROM memory_entries "
                "WHERE workspace = 'ws-1' AND embedding IS NOT NULL "
                f"ORDER BY embedding <=> '{_literal(0.5)}'::vector LIMIT 5"
            )
        )

        assert "workspace" in plan, f"scope is not in the plan:\n{plan}"


class TestOneIndexStrategy:
    @pytest.mark.ac("SPEC-083026-4b70/AC-5")
    async def test_the_index_is_hnsw_over_the_cosine_operator_class(self, conn) -> None:
        definition = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_memory_entries_embedding_hnsw'"
        )

        assert definition is not None, "migration 029 did not create the index"
        assert "USING hnsw" in definition
        assert "vector_cosine_ops" in definition

    @pytest.mark.ac("SPEC-083026-4b70/AC-5")
    async def test_it_is_named_the_way_011_names_the_learnings_one(self, conn) -> None:
        """A second naming convention for the same access pattern is the
        per-table lookup ADR-082326-8194 argued against."""
        names = {
            record["indexname"]
            for record in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE indexname LIKE '%_embedding_hnsw'"
            )
        }

        assert {"ix_memory_entries_embedding_hnsw", "ix_learnings_embedding_hnsw"} <= names


#: Read from the tree rather than from a database: these are claims in source,
#: and the point of AC-6 is that a comment contradicting the schema is what let
#: the defect survive six migrations.
class TestNothingStillDescribesItWrongly:
    @pytest.mark.ac("SPEC-083026-4b70/AC-6")
    def test_001_does_not_claim_it_produced_a_vector_column(self) -> None:
        source = (REPO_ROOT / "alembic" / "versions" / "001_initial_memory_schema.py").read_text(
            encoding="utf-8"
        )

        assert "# vector(1536) — managed by pgvector" not in source, (
            "001's inline comment asserted an outcome the next line failed to produce"
        )

    @pytest.mark.ac("SPEC-083026-4b70/AC-6")
    def test_no_artefact_names_a_migration_file_that_does_not_exist(self) -> None:
        """`vectors.py` cited `007_memory_embedding_columns.py`. The file is
        `011_memory_embedding_columns.py`, and 007 is a different revision."""
        versions = REPO_ROOT / "alembic" / "versions"
        source = (
            REPO_ROOT / "packages" / "maistro-core" / "src" / "maistro" / "memory" / "vectors.py"
        ).read_text(encoding="utf-8")

        # By basename, and via a regex rather than whitespace splitting: the
        # citations are written `alembic/versions/011_....py` inside backticks,
        # so a token filter keyed on a leading digit matches none of them --
        # which is how the first draft of this test passed while `vectors.py`
        # still named a file that does not exist.
        cited = {Path(match).name for match in re.findall(r"[\w/]+\.py", source)}
        missing = sorted(
            name
            for name in cited
            if re.match(r"^\d{3}[_.]", name) and not (versions / name).exists()
        )

        assert missing == [], f"vectors.py cites migration files that do not exist: {missing}"

    @pytest.mark.ac("SPEC-083026-4b70/AC-6")
    def test_the_declared_width_matches_what_the_repair_creates(self) -> None:
        """The same equality `test_memory_embeddings.py` holds for 011, for the
        same reason: a constant that drifted from the DDL is a check that passes
        while every write fails."""
        migration = (
            REPO_ROOT / "alembic" / "versions" / "029_memory_entries_embedding_is_a_vector.py"
        ).read_text(encoding="utf-8")

        assert f"_DIMENSIONS = {EMBEDDING_DIMENSIONS}" in migration
