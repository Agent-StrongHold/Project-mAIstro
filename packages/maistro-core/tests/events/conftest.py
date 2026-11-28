"""Canonical Event fixtures use the official migration, never runtime DDL."""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _canonical_event_migration_sql() -> str:
    path = Path(__file__).resolve().parents[4] / "alembic/versions/030_canonical_event_envelope.py"
    spec = importlib.util.spec_from_file_location("canonical_event_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    return output.getvalue()


@pytest.fixture
async def canonical_event_schema():
    """Apply revision 030 in an isolated schema on the real test server.

    The full chain is separately exercised by tests/migrations. Rendering this
    official revision also supports the plain-Postgres durable-events CI job,
    which has no pgvector extension and cannot apply unrelated migrations.
    """
    import asyncpg

    dsn = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            raise RuntimeError("MAISTRO_REQUIRE_PG_LEGS needs MAISTRO_TEST_DATABASE_URL")
        pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; migration proof needs PostgreSQL")
    schema = f"canonical_event_{uuid4().hex}"
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        await conn.execute(_canonical_event_migration_sql())
        yield schema
    finally:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
