"""Migration 063 and `pg_store._PG_SCHEMA` must describe the same three tables.

The Goal tables ship twice. A managed deployment gets them from Alembic
revision 063; tests and single-command dev runs get them from
`ensure_goal_schema` — the same dual-ship, and the same drift risk, the event
stores carry (compared by `tests/migrations/test_event_schema_agreement.py`).
The DDL is written out twice on purpose — a migration has to keep creating
what it created on the day it ran, so it cannot import live application code —
and duplicated DDL drifts.

Drift here is not cosmetic. `parent_goal_id`'s foreign key with ON DELETE
CASCADE *is* the Subgoal lineage contract (#1572): if migration 063 ever grew
a RESTRICT while `_PG_SCHEMA` kept the CASCADE, every conformance test would
pass against the store's own schema and a managed deployment would delete
Goals differently than every test environment. So this compares the two
against a real server's catalogue — columns, types, nullability, defaults,
primary keys, foreign keys with their delete actions, and indexes — rather
than diffing the two texts, which would agree on formatting and miss the
semantics.

Both sides render into throwaway schemas of their own (the migration offline
via `alembic --sql`, which does not connect), so neither a migrated database
nor its rows are touched: the comparison is self-contained on any server the
suite is pointed at.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: The tables migration 063 creates. Spelled out rather than derived from the
#: catalogue: a comparison of "the tables that exist" passes vacuously when
#: neither side creates anything.
GOAL_TABLES = (
    "canonical_goals",
    "canonical_goal_revisions",
    "canonical_goal_transitions",
)

#: Each side rendered/applied on its own: `alembic upgrade a:b --sql` renders
#: the revisions strictly between the two, so rendering `063:head` would drag
#: every later revision into the comparison — and there must not be one that
#: recreates these tables.
GOAL_REVISION_RANGE = "062:063"


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    `MAISTRO_REQUIRE_PG_LEGS` is set by the CI jobs that own a PostgreSQL
    service. There, "no URL" means the job is misconfigured, and skipping would
    leave the job green with the comparison never made.
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the Goal schema comparison cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; comparing catalogues needs a real server")


def _migration_ddl() -> str:
    """Render revision 063 with `alembic --sql`, which does not connect.

    Offline mode still builds a URL through `DatabaseSettings`, so the DB_* vars
    below only have to parse — nothing dials them. Rendering the real migration
    rather than re-typing its DDL is the point: a change to
    `alembic/versions/063_canonical_goals.py` reaches this test.
    """
    env = {
        **os.environ,
        "DB_HOST": "offline.invalid",
        "DB_PORT": "5432",
        "DB_NAME": "offline",
        "DB_USER": "offline",
        "DB_PASSWORD": "offline",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", GOAL_REVISION_RANGE, "--sql"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return result.stdout


def _executable_statements(ddl: str) -> list[str]:
    """Strip comments and transaction/bookkeeping noise from rendered DDL.

    What survives is only the CREATE TABLE / CREATE INDEX revision 063 emits.
    `alembic_version` is dropped because it is alembic's own bookkeeping, not
    part of the schema under comparison.
    """
    without_comments = re.sub(r"^--.*$", "", ddl, flags=re.MULTILINE)
    statements = []
    for raw in without_comments.split(";"):
        statement = raw.strip()
        if not statement:
            continue
        if re.match(r"^(BEGIN|COMMIT)\b", statement, re.IGNORECASE):
            continue
        if "alembic_version" in statement:
            continue
        statements.append(statement)
    if not statements:  # pragma: no cover - a silent empty render would pass everything
        msg = "alembic rendered no DDL for revision 063; the comparison would be vacuous"
        raise AssertionError(msg)
    return statements


async def _catalogue(conn, schema: str) -> dict[str, object]:
    """Columns, keys and indexes for the Goal tables in one schema."""
    columns = await conn.fetch(
        """SELECT table_name, column_name, data_type, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema = $1 AND table_name = ANY($2::text[])
           ORDER BY table_name, column_name""",
        schema,
        list(GOAL_TABLES),
    )
    # Primary keys by *ordered* column list: (goal_id, revision) and
    # (revision, goal_id) index the same rows but are not the same key.
    primary_keys = await conn.fetch(
        """SELECT c.relname AS table_name,
                  array_agg(a.attname ORDER BY k.ord) AS columns
           FROM pg_constraint con
           JOIN pg_class c ON c.oid = con.conrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
           JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
           WHERE con.contype = 'p' AND n.nspname = $1 AND c.relname = ANY($2::text[])
           GROUP BY c.relname
           ORDER BY c.relname""",
        schema,
        list(GOAL_TABLES),
    )
    # Foreign keys with their ON DELETE action: the Subgoal lineage contract
    # lives in the CASCADE, not in the mere existence of the constraint. Every
    # Goal FK is single-column, so the catalogue's first-key arrays name the
    # columns directly.
    foreign_keys = await conn.fetch(
        """SELECT c.relname AS table_name,
                  sa.attname AS column_name,
                  dst.relname AS ref_table,
                  da.attname AS ref_column,
                  con.confdeltype AS on_delete
           FROM pg_constraint con
           JOIN pg_class c ON c.oid = con.conrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN pg_class dst ON dst.oid = con.confrelid
           JOIN pg_attribute sa ON sa.attrelid = c.oid AND sa.attnum = con.conkey[1]
           JOIN pg_attribute da ON da.attrelid = dst.oid AND da.attnum = con.confkey[1]
           WHERE con.contype = 'f' AND n.nspname = $1 AND c.relname = ANY($2::text[])
           ORDER BY c.relname""",
        schema,
        list(GOAL_TABLES),
    )
    indexes = await conn.fetch(
        """SELECT tablename, indexname, indexdef FROM pg_indexes
           WHERE schemaname = $1 AND tablename = ANY($2::text[])
           ORDER BY tablename, indexname""",
        schema,
        list(GOAL_TABLES),
    )
    return {
        "columns": [tuple(row) for row in columns],
        "primary_keys": [(row["table_name"], list(row["columns"])) for row in primary_keys],
        "foreign_keys": [
            (
                row["table_name"],
                [row["column_name"]],
                row["ref_table"],
                [row["ref_column"]],
                # "char" comes back as bytes; the catalogue code for CASCADE is b"c".
                (row["on_delete"] or b"").decode(),
            )
            for row in foreign_keys
        ],
        # indexdef embeds the schema name, which differs by construction.
        "indexes": [
            (row["tablename"], row["indexname"], row["indexdef"].replace(f"{schema}.", ""))
            for row in indexes
        ],
    }


@pytest.fixture
async def built_schemas():
    """Build both schemas side by side and hand back their catalogues."""
    import asyncpg

    from maistro.goals.pg_store import _PG_SCHEMA

    conn = await asyncpg.connect(_require_postgres())
    try:
        for schema in ("goal_agree_migration", "goal_agree_ensure"):
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.execute(f'CREATE SCHEMA "{schema}"')

        await conn.execute("SET search_path TO goal_agree_migration")
        for statement in _executable_statements(_migration_ddl()):
            await conn.execute(statement)

        await conn.execute("SET search_path TO goal_agree_ensure")
        await conn.execute(_PG_SCHEMA)

        await conn.execute("SET search_path TO public")
        yield (
            await _catalogue(conn, "goal_agree_migration"),
            await _catalogue(conn, "goal_agree_ensure"),
        )
    finally:
        await conn.execute("SET search_path TO public")
        for schema in ("goal_agree_migration", "goal_agree_ensure"):
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()


class TestMigration063MatchesEnsureSchema:
    def test_both_sides_create_all_three_tables(self, built_schemas):
        """Guards the comparison itself: equal-and-empty is not agreement."""
        migration, ensure = built_schemas
        for catalogue in (migration, ensure):
            created = {table for table, *_ in catalogue["columns"]}
            assert created == set(GOAL_TABLES)

    def test_columns_types_nullability_and_defaults_agree(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["columns"] == ensure["columns"]

    def test_primary_keys_agree_including_column_order(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["primary_keys"] == ensure["primary_keys"]

    def test_the_revision_chain_key_is_the_natural_composite_one(self, built_schemas):
        """Named separately from the generic comparison above because this is
        append-only's teeth (#1572): (goal_id, revision) is what makes a
        revision row immutable under INSERT, and both DDL sources must pick
        it over any surrogate key."""
        for catalogue in built_schemas:
            keys = dict(catalogue["primary_keys"])
            assert keys["canonical_goal_revisions"] == ["goal_id", "revision"]

    def test_foreign_keys_agree_including_the_cascade(self, built_schemas):
        """The Subgoal lineage and append-only children are FK contracts; the
        ON DELETE action is part of the contract, not an implementation
        detail ('c' is the catalogue code for CASCADE)."""
        migration, ensure = built_schemas
        assert migration["foreign_keys"] == ensure["foreign_keys"]
        foreign_keys = {fk[0]: fk for fk in ensure["foreign_keys"]}
        assert set(foreign_keys) == {
            "canonical_goals",
            "canonical_goal_revisions",
            "canonical_goal_transitions",
        }, foreign_keys
        lineage = foreign_keys.get("canonical_goals")
        assert lineage is not None
        assert lineage[1] == ["parent_goal_id"] and lineage[2] == "canonical_goals"
        assert lineage[4] == "c"
        for child in ("canonical_goal_revisions", "canonical_goal_transitions"):
            child_fk = foreign_keys[child]
            assert child_fk[2] == "canonical_goals" and child_fk[4] == "c"

    def test_indexes_agree(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["indexes"] == ensure["indexes"]
