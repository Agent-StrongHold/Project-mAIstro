"""Migration 072 and `pg_store._PG_SCHEMA` must describe the same two tables.

The working-log tables ship twice. A managed deployment gets them from Alembic
revision 072; tests and single-command dev runs get them from
`ensure_working_log_schema` — the same dual-ship, and the same drift risk, the
Goal tables carry (compared by
`packages/maistro-core/tests/goals/test_goal_pg_schema_agreement.py` for
revision 063). The DDL is written out twice on purpose — a migration has to
keep creating what it created on the day it ran, so it cannot import live
application code — and duplicated DDL drifts.

Drift here is not cosmetic. `seq` being an identity column *is* the
append-only contract: the log assigns positions on `append` and a caller's
`seq` is ignored, which is exactly what the conformance suite pins. If
migration 072 ever grew a plain `BIGINT PRIMARY KEY` while `_PG_SCHEMA` kept
the identity, a managed deployment would hand out NULLs or require explicit
positions where every test environment assigns them. So this compares the two
against a real server's catalogue — columns, types, nullability, defaults,
identity generation, primary keys, and indexes — rather than diffing the two
texts, which would agree on formatting and miss the semantics.

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

#: The tables migration 072 creates. Spelled out rather than derived from the
#: catalogue: a comparison of "the tables that exist" passes vacuously when
#: neither side creates anything.
WORKING_LOG_TABLES = (
    "workspace_working_log",
    "workspace_working_results",
)

#: Each side rendered/applied on its own: `alembic upgrade a:b --sql` renders
#: the revisions strictly between the two, so rendering `072:head` would drag
#: every later revision into the comparison — and there must not be one that
#: recreates these tables.
WORKING_LOG_REVISION_RANGE = "071:072"


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
            "the working-log schema comparison cannot run and must not be silently "
            "skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; comparing catalogues needs a real server")


def _migration_ddl() -> str:
    """Render revision 072 with `alembic --sql`, which does not connect.

    Offline mode still builds a URL through `DatabaseSettings`, so the DB_* vars
    below only have to parse — nothing dials them. Rendering the real migration
    rather than re-typing its DDL is the point: a change to
    `alembic/versions/072_workspace_working_log.py` reaches this test.
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
        [sys.executable, "-m", "alembic", "upgrade", WORKING_LOG_REVISION_RANGE, "--sql"],
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

    What survives is only the CREATE TABLE / CREATE INDEX revision 072 emits.
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
        msg = "alembic rendered no DDL for revision 072; the comparison would be vacuous"
        raise AssertionError(msg)
    return statements


async def _catalogue(conn, schema: str) -> dict[str, object]:
    """Columns, keys and indexes for the working-log tables in one schema."""
    columns = await conn.fetch(
        """SELECT table_name, column_name, data_type, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema = $1 AND table_name = ANY($2::text[])
           ORDER BY table_name, column_name""",
        schema,
        list(WORKING_LOG_TABLES),
    )
    # The identity property on `seq` is compared separately: the default
    # columns projection above reads NULL for both an identity column and a
    # plain one, which would let the append-only position contract drift
    # silently. `identity_generation` is 'a' (ALWAYS) only where the DDL says
    # GENERATED ALWAYS AS IDENTITY.
    identities = await conn.fetch(
        """SELECT table_name, column_name, identity_generation
           FROM information_schema.columns
           WHERE table_schema = $1 AND table_name = ANY($2::text[])
             AND identity_generation IS NOT NULL
           ORDER BY table_name, column_name""",
        schema,
        list(WORKING_LOG_TABLES),
    )
    # Primary keys by *ordered* column list: (workspace_id, result_id) and
    # (result_id, workspace_id) index the same rows but are not the same key.
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
        list(WORKING_LOG_TABLES),
    )
    # Foreign keys: the log carries none by design — a Workspace row going
    # away is answered by the driven `purge_workspace`, not by a cascade this
    # schema must agree on with the SQLite twin, which cannot declare one.
    foreign_keys = await conn.fetch(
        """SELECT c.relname AS table_name
           FROM pg_constraint con
           JOIN pg_class c ON c.oid = con.conrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE con.contype = 'f' AND n.nspname = $1 AND c.relname = ANY($2::text[])""",
        schema,
        list(WORKING_LOG_TABLES),
    )
    indexes = await conn.fetch(
        """SELECT tablename, indexname, indexdef FROM pg_indexes
           WHERE schemaname = $1 AND tablename = ANY($2::text[])
           ORDER BY tablename, indexname""",
        schema,
        list(WORKING_LOG_TABLES),
    )
    return {
        "columns": [tuple(row) for row in columns],
        "identities": [tuple(row) for row in identities],
        "primary_keys": [(row["table_name"], list(row["columns"])) for row in primary_keys],
        "foreign_keys": [row["table_name"] for row in foreign_keys],
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

    from maistro.memory.working.pg_store import _PG_SCHEMA

    conn = await asyncpg.connect(_require_postgres())
    try:
        for schema in ("working_log_agree_migration", "working_log_agree_ensure"):
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.execute(f'CREATE SCHEMA "{schema}"')

        await conn.execute("SET search_path TO working_log_agree_migration")
        for statement in _executable_statements(_migration_ddl()):
            await conn.execute(statement)

        await conn.execute("SET search_path TO working_log_agree_ensure")
        await conn.execute(_PG_SCHEMA)

        await conn.execute("SET search_path TO public")
        yield (
            await _catalogue(conn, "working_log_agree_migration"),
            await _catalogue(conn, "working_log_agree_ensure"),
        )
    finally:
        await conn.execute("SET search_path TO public")
        for schema in ("working_log_agree_migration", "working_log_agree_ensure"):
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()


class TestMigration072MatchesEnsureSchema:
    def test_both_sides_create_both_tables(self, built_schemas):
        """Guards the comparison itself: equal-and-empty is not agreement."""
        migration, ensure = built_schemas
        for catalogue in (migration, ensure):
            created = {table for table, *_ in catalogue["columns"]}
            assert created == set(WORKING_LOG_TABLES)

    def test_columns_types_nullability_and_defaults_agree(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["columns"] == ensure["columns"]

    def test_the_log_position_is_identity_on_both_sides(self, built_schemas):
        """Named separately because this is append-only's teeth (#301): `seq`
        is GENERATED ALWAYS on both sides, so the log assigns positions on
        `append` and a caller-chosen position is ignored — the exact rule the
        conformance suite pins."""
        for catalogue in built_schemas:
            assert catalogue["identities"] == [("workspace_working_log", "seq", "ALWAYS")]

    def test_primary_keys_agree_including_column_order(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["primary_keys"] == ensure["primary_keys"]
        for catalogue in built_schemas:
            keys = dict(catalogue["primary_keys"])
            assert keys["workspace_working_log"] == ["seq"]
            assert keys["workspace_working_results"] == ["workspace_id", "result_id"]

    def test_no_foreign_keys_on_either_side(self, built_schemas):
        """Retention is the driven `purge_workspace`, not a cascade: neither
        side may grow a FK the SQLite twin cannot declare."""
        migration, ensure = built_schemas
        assert migration["foreign_keys"] == []
        assert ensure["foreign_keys"] == []

    def test_indexes_agree(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["indexes"] == ensure["indexes"]
        for catalogue in built_schemas:
            names = {index[1] for index in catalogue["indexes"]}
            assert "idx_workspace_working_log_ws" in names
