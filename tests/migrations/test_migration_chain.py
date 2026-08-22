"""The alembic chain must apply to an empty PostgreSQL database (#177).

Before this, it could not. `alembic upgrade head` failed at migration 003 on a
foreign key to `orgs.id` — a table no migration creates and no model defines —
and because alembic runs the chain under transactional DDL, 001 and 002 rolled
back with it. A fresh database ended with **zero** tables, at the first command
of every documented Postgres setup path.

It went unnoticed because nothing ever ran it: no workflow had a `postgres`
service, and `psycopg2` was not a declared dependency, so the chain failed with
`ModuleNotFoundError` before it could reach the real error. A migration chain
that has never been applied has never been able to fail a build.

These tests need a real server and are skipped without one, so `MAISTRO_TEST_
DATABASE_URL` is what makes them run. `ci.yml`'s `migrations` job sets it
against a `postgres:17` service; locally, point it at any throwaway database.
Skipping when it is unset is deliberate — the alternative is a suite that
cannot run on a laptop — but the skip is what made this bug survive, so the
CI job is the half that matters.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)

#: Every table the chain is expected to leave behind, `alembic_version` aside.
#: Spelled out rather than counted: a count passes when one table is dropped and
#: another added, which is precisely the kind of change that should be read.
EXPECTED_TABLES = frozenset(
    {
        "asset_definitions",
        "asset_instances",
        "asset_sheets",
        "books",
        "child_profiles",
        "design_outputs",
        "design_projects",
        "episodic_memories",
        "knowledge_nodes",
        "learnings",
        "memory_entries",
        "outcomes",
        # Added by 004_quota_sessions (#182): the two tables `PgQuotaTracker`
        # and `PgSessionStore` were already querying and no revision created.
        "quota_usage",
        "sessions",
        "tasks",
    }
)


def _alembic_env() -> dict[str, str]:
    """alembic/env.py reads DB_* through `DatabaseSettings`, not DATABASE_URL."""
    from urllib.parse import urlsplit

    parts = urlsplit(DATABASE_URL)
    return {
        **os.environ,
        "DB_HOST": parts.hostname or "127.0.0.1",
        "DB_PORT": str(parts.port or 5432),
        "DB_NAME": (parts.path or "/postgres").lstrip("/"),
        "DB_USER": parts.username or "postgres",
        "DB_PASSWORD": parts.password or "",
    }


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _tables() -> set[str]:
    import psycopg2

    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select tablename from pg_tables where schemaname = 'public'")
        return {row[0] for row in cur.fetchall()}


@pytest.fixture
def empty_database():
    """Start each test from `base`, so one failure cannot cascade into the next.

    `downgrade base` drops what the *chain* created and nothing else, so a table
    made outside it — `ensure_event_schema` during development, a hand-run
    CREATE — survives and lands in the exact-set assertions below as unexplained
    extra items. That reads exactly like the chain creating tables it should
    not, which is the defect these tests exist to catch, so it is worth one
    explicit check that says which it is.
    """
    _alembic("downgrade", "base")
    residue = _tables() - {"alembic_version"}
    assert not residue, (
        f"the test database holds tables the migration chain did not create: "
        f"{sorted(residue)}. Drop them — the assertions below compare an exact "
        f"set, and residue here is indistinguishable from a chain defect."
    )
    yield
    _alembic("downgrade", "base")


class TestTheChainApplies:
    def test_upgrade_head_succeeds_on_an_empty_database(self, empty_database) -> None:
        """The exact command the README gives, against the state it assumes."""
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr

    def test_upgrade_head_creates_every_expected_table(self, empty_database) -> None:
        """Not merely "did not raise". The original failure left zero tables
        while the process still had to be read to know that."""
        _alembic("upgrade", "head")
        assert _tables() - {"alembic_version"} == EXPECTED_TABLES

    def test_no_migration_references_a_table_the_chain_does_not_create(
        self, empty_database
    ) -> None:
        """The specific defect: a foreign key to `orgs.id`, which nothing makes.

        Asserted against the live catalog rather than by reading the migration
        source, so it also covers a reference introduced by a future migration.
        """
        _alembic("upgrade", "head")
        import psycopg2

        tables = _tables()
        # Without this the test passes vacuously on exactly the bug it is for:
        # the broken chain left zero tables, so there were zero foreign keys and
        # `set() <= set()` held. An empty database must fail here, not pass.
        assert tables >= EXPECTED_TABLES, "the chain did not reach head; nothing to check"

        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """
                select conrelid::regclass::text, confrelid::regclass::text
                from pg_constraint
                where contype = 'f' and connamespace = 'public'::regnamespace
                """
            )
            references = {target for _, target in cur.fetchall()}
        assert references, "no foreign keys at all; this check would prove nothing"
        assert references <= tables, f"foreign keys to absent tables: {references - tables}"

    def test_the_chain_round_trips(self, empty_database) -> None:
        """`downgrade base` then `upgrade head` must reach the same schema.

        A downgrade that does not fully undo its upgrade leaves the next
        migration to land on a shape nobody has tested.
        """
        _alembic("upgrade", "head")
        first = _tables()
        assert _alembic("downgrade", "base").returncode == 0
        assert _tables() - {"alembic_version"} == set()
        assert _alembic("upgrade", "head").returncode == 0
        assert _tables() == first


class TestIndexIntent:
    def test_the_recency_indexes_are_actually_descending(self, empty_database) -> None:
        """`postgresql_order_by=` is not a real argument — SQLAlchemy raises on
        it rather than ignoring it, so this was unreachable behind the foreign
        key error. Read from the catalog, because the point is what the server
        built, not what the migration asked for.
        """
        _alembic("upgrade", "head")
        import psycopg2

        # Only these two. `ix_outcomes_created_at` (migration 001) is a plain
        # ascending index and never claimed otherwise — sweeping every
        # `%_created_at` index into this assertion tests a decision nobody made.
        descending = ("idx_design_projects_created_at", "idx_design_outputs_created_at")
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public' and indexname = any(%s)",
                (list(descending),),
            )
            definitions = dict(cur.fetchall())
        assert set(definitions) == set(descending), f"missing: {set(descending) - set(definitions)}"
        for name, definition in definitions.items():
            assert "created_at DESC" in definition, f"{name} is not descending: {definition}"
