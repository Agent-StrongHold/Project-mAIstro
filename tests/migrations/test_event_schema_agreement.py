"""Migration 004 and `pg_stores._SCHEMA` must describe the same three tables.

`PgEventLog`/`PgTriggerStore`/`PgInvocationStore` create their tables two ways.
Alembic revision 004 is what a real deployment applies; `ensure_event_schema()`
is what tests and single-process dev runs call. The DDL is written out twice on
purpose — a migration has to keep creating what it created on the day it ran,
so it cannot import live application code — and duplicated DDL drifts.

Drift here is not cosmetic. The composite primary key on `handler_invocations`
*is* the idempotency guarantee (#135): if the migration ever grew a surrogate
key while `_SCHEMA` kept the composite one, every test would pass against
`ensure_event_schema()` and production would silently run a redelivered event
twice. So this compares the two against a real server's catalogue — columns,
types, nullability, defaults, primary keys and indexes — rather than diffing
the two texts, which would agree on formatting and miss the semantics.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: The three tables revision 004 creates. Spelled out rather than derived from
#: the catalogue: a test that asks "are the tables that exist equal?" passes
#: vacuously when neither side creates anything.
EVENT_TABLES = ("event_log", "handler_invocations", "trigger_definitions")


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed.

    `MAISTRO_REQUIRE_PG_LEGS` is set by the `durable-events` CI job, which owns
    a postgres service container. There, "no URL" means the job is misconfigured,
    and skipping would leave it green with the comparison never made.
    """
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the catalogue comparison cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; comparing catalogues needs a real server")


def _migration_ddl() -> str:
    """Render revision 004 with `alembic --sql`, which does not connect.

    Offline mode still builds a URL through `DatabaseSettings`, so the DB_* vars
    below only have to parse — nothing dials them. Rendering the real migration
    rather than re-typing its DDL is the point: a change to
    `alembic/versions/004_durable_events.py` reaches this test.
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
        [sys.executable, "-m", "alembic", "upgrade", "003:004", "--sql"],
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

    What survives is only the CREATE TABLE / CREATE INDEX this revision emits.
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
        msg = "alembic rendered no DDL for revision 004; the comparison would be vacuous"
        raise AssertionError(msg)
    return statements


async def _catalogue(conn, schema: str) -> dict[str, object]:
    """Columns, primary keys and indexes for the event tables in one schema."""
    columns = await conn.fetch(
        """SELECT table_name, column_name, data_type, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema = $1 AND table_name = ANY($2::text[])
           ORDER BY table_name, column_name""",
        schema,
        list(EVENT_TABLES),
    )
    # Primary keys by *ordered* column list: (trigger_id, event_id) and
    # (event_id, trigger_id) index the same rows but are not the same key.
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
        list(EVENT_TABLES),
    )
    indexes = await conn.fetch(
        """SELECT tablename, indexname, indexdef FROM pg_indexes
           WHERE schemaname = $1 AND tablename = ANY($2::text[])
           ORDER BY tablename, indexname""",
        schema,
        list(EVENT_TABLES),
    )

    def _strip_schema(value: object) -> object:
        # A serial column's default is `nextval('<schema>.event_log_id_seq')`,
        # so the schema name is embedded in the value being compared. Both
        # sides do produce a sequence — that agreement is the finding; only the
        # qualifier differs by construction.
        return value.replace(f"{schema}.", "") if isinstance(value, str) else value

    return {
        "columns": [tuple(_strip_schema(value) for value in row) for row in columns],
        "primary_keys": [(row["table_name"], list(row["columns"])) for row in primary_keys],
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

    from maistro.events.pg_stores import _SCHEMA

    conn = await asyncpg.connect(_require_postgres())
    try:
        for schema in ("agree_migration", "agree_ensure"):
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.execute(f'CREATE SCHEMA "{schema}"')

        await conn.execute("SET search_path TO agree_migration")
        for statement in _executable_statements(_migration_ddl()):
            await conn.execute(statement)

        await conn.execute("SET search_path TO agree_ensure")
        await conn.execute(_SCHEMA)

        await conn.execute("SET search_path TO public")
        yield (
            await _catalogue(conn, "agree_migration"),
            await _catalogue(conn, "agree_ensure"),
        )
    finally:
        for schema in ("agree_migration", "agree_ensure"):
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()


class TestMigrationMatchesEnsureSchema:
    def test_the_migration_creates_all_three_tables(self, built_schemas):
        """Guards the comparison itself: equal-and-empty is not agreement."""
        migration, _ = built_schemas
        created = {table for table, *_ in migration["columns"]}
        assert created == set(EVENT_TABLES)

    def test_columns_types_nullability_and_defaults_agree(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["columns"] == ensure["columns"]

    def test_primary_keys_agree_including_column_order(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["primary_keys"] == ensure["primary_keys"]

    def test_the_invocation_idempotency_key_is_the_composite_one(self, built_schemas):
        """Named separately from the generic comparison above because this is
        the guarantee #135 exists for. Both sides agreeing on a *surrogate* key
        would pass the previous test and lose the guarantee."""
        for catalogue in built_schemas:
            keys = dict(catalogue["primary_keys"])
            assert keys["handler_invocations"] == ["trigger_id", "event_id"]

    def test_indexes_agree(self, built_schemas):
        migration, ensure = built_schemas
        assert migration["indexes"] == ensure["indexes"]
