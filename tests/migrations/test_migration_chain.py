"""The alembic chain must apply to an empty PostgreSQL database (#177).

For a long time it could not: migration 003 declared foreign keys to `orgs.id`
and `teams.id`, and because alembic runs the chain under transactional DDL, 003
failing rolled 001 and 002 back with it. A fresh database ended with **zero**
tables, at the first command of every documented Postgres setup path. The fix
that landed creates those two scope tables in 003 itself, as the minimal
anchors ADR-068's soft `org` and `team` axes need.

It went unnoticed because nothing ever ran it: no workflow had a `postgres`
service, and the synchronous driver alembic needs was declared nowhere, so the
chain died with `ModuleNotFoundError` before it could reach the real error. A
migration chain that has never been applied has never been able to fail a
build. This suite is the half that keeps that from recurring — it asserts on
the **live catalog** rather than on the migration source, so it also sees a
future migration that reintroduces the shape.

Needs a real server and skips without one, so `MAISTRO_TEST_DATABASE_URL` is
what makes it run; `ci.yml`'s `postgres` job sets it against the same service
it already applies the chain to. Skipping when it is unset is deliberate — the
alternative is a suite that cannot run on a laptop — but the skip is exactly
what let the original bug survive, so the CI wiring is the part that matters.
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
#: Spelled out rather than counted: a count still passes when one table is
#: dropped and another added, which is precisely the change that wants reading.
EXPECTED_TABLES = frozenset(
    {
        "agents",
        "asset_definitions",
        "asset_instances",
        "asset_sheets",
        "audit_log",
        "books",
        "child_profiles",
        "design_outputs",
        "design_projects",
        "episodic_memories",
        "event_log",
        "handler_invocations",
        "knowledge_nodes",
        "learnings",
        "memory_entries",
        "orgs",
        "outcomes",
        "prompts",
        "quota_usage",
        "security_rate_limits",
        "security_strikes",
        "security_violations",
        "sessions",
        "tasks",
        "teams",
        "trigger_definitions",
    }
)


def _alembic_env() -> dict[str, str]:
    """alembic/env.py resolves one URL through `require_database_url` (#187)."""
    return {**os.environ, "DATABASE_URL": DATABASE_URL}


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


def _query(sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    # psycopg 3: the declared synchronous driver. A bare `postgresql://` URL
    # resolves to psycopg2 inside SQLAlchemy, which is why `to_sync_url` names
    # this one explicitly — and why importing it by name here is the honest
    # spelling rather than reaching for whatever happens to be installed.
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return list(cur.fetchall())


def _tables() -> set[str]:
    return {
        str(row[0])
        for row in _query("select tablename from pg_tables where schemaname = %s", ("public",))
    }


@pytest.fixture
def empty_database():
    """Start each test from `base`, so one failure cannot cascade into the next."""
    _alembic("downgrade", "base")
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
        """The specific defect: a foreign key to a table nothing makes.

        Asserted against the live catalog rather than by reading the migration
        source, so it also covers a reference introduced by a future migration.
        """
        _alembic("upgrade", "head")
        tables = _tables()
        # Without this the test passes vacuously on exactly the bug it is for:
        # the broken chain left zero tables, so there were zero foreign keys and
        # `set() <= set()` held. An empty database must fail here, not pass.
        assert tables >= EXPECTED_TABLES, "the chain did not reach head; nothing to check"

        references = {
            str(row[1])
            for row in _query(
                """
                select conrelid::regclass::text, confrelid::regclass::text
                from pg_constraint
                where contype = 'f' and connamespace = 'public'::regnamespace
                """
            )
        }
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
        # Only these two. `ix_outcomes_created_at` (migration 001) is a plain
        # ascending index and never claimed otherwise — sweeping every
        # `%_created_at` index into this assertion tests a decision nobody made.
        descending = ("idx_design_projects_created_at", "idx_design_outputs_created_at")
        definitions = {
            str(name): str(definition)
            for name, definition in _query(
                "select indexname, indexdef from pg_indexes "
                "where schemaname = 'public' and indexname = any(%s)",
                (list(descending),),
            )
        }
        assert set(definitions) == set(descending), f"missing: {set(descending) - set(definitions)}"
        for name, definition in definitions.items():
            assert "created_at DESC" in definition, f"{name} is not descending: {definition}"
