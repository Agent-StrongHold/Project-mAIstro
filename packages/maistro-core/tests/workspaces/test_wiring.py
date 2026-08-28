"""Which Workspace store each backend actually yields (#516).

`wire_workspace_store` is the only thing standing between a `postgresql://`
deployment and Workspaces that vanish on restart, and the way that goes wrong
is silent: the selection falls back and everything still works, until the
process restarts. So the selection is asserted rather than assumed -- including
the fallback, which must warn.
"""

from __future__ import annotations

import logging
import os

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.testing.postgres import postgres_dsn
from maistro.workspaces.store import InMemoryWorkspaceStore, WorkspaceStore
from maistro.workspaces.wiring import WORKSPACE_PG_TABLES, wire_workspace_store


async def test_no_backend_yields_the_in_memory_reference() -> None:
    store = await wire_workspace_store(None, project_store=InMemoryProjectScopeStore())

    assert isinstance(store, InMemoryWorkspaceStore)


async def test_a_sqlite_connection_yields_the_sqlite_store_with_its_schema(tmp_path) -> None:
    import aiosqlite

    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    conn = await aiosqlite.connect(tmp_path / "wired.db")
    try:
        store = await wire_workspace_store(conn, project_store=InMemoryProjectScopeStore())

        assert isinstance(store, SqliteWorkspaceStore)
        # `ensure_schema` ran: the tables exist without the caller doing anything.
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'canonical_workspace%'"
        ) as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        assert tables == {"canonical_workspaces", "canonical_workspace_memberships"}
    finally:
        await conn.close()


async def test_the_selected_store_files_root_projects_in_the_store_it_was_given() -> None:
    """The reason this takes `project_store` rather than resolving one.

    A Workspace whose Root Project is filed in a different database is a
    Workspace whose Runs cannot be filed, and nothing about the Workspace row
    would show it.
    """
    scope_store = InMemoryProjectScopeStore()
    store = await wire_workspace_store(None, project_store=scope_store)

    workspace = await store.create(creator_user_id="someone", name="Wired")

    assert store.project_store is scope_store
    assert (await scope_store.root_for_workspace(workspace.workspace_id)).is_root


class _UnmigratedPool:
    """A pool whose database has none of the Workspace tables."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def fetchval(self, _query: str, argument: str) -> bool:
        self.asked.append(argument)
        return False


async def test_an_unmigrated_postgres_pool_falls_back_and_says_so(caplog) -> None:
    """Silent fallback here is the shape of #122: a durable deployment quietly
    running on ephemeral stores, discovered at the next restart."""
    pool = _UnmigratedPool()

    with caplog.at_level(logging.WARNING, logger="maistro.workspaces.wiring"):
        store = await wire_workspace_store(
            None, project_store=InMemoryProjectScopeStore(), pg_pool=pool
        )

    assert isinstance(store, InMemoryWorkspaceStore)
    assert pool.asked == [f"public.{table}" for table in WORKSPACE_PG_TABLES]
    assert "alembic upgrade head" in caplog.text
    for table in WORKSPACE_PG_TABLES:
        assert table in caplog.text


async def test_a_migrated_postgres_pool_yields_the_postgres_store() -> None:
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL selection cannot be checked and must not be "
                "silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    from maistro.workspaces.pg_store import PgWorkspaceStore

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        store = await wire_workspace_store(
            None, project_store=InMemoryProjectScopeStore(), pg_pool=pool
        )

        assert isinstance(store, PgWorkspaceStore)
    finally:
        await pool.close()


def test_every_implementation_satisfies_the_protocol() -> None:
    """`WorkspaceStore` is a runtime-checkable Protocol, so this is a real
    structural check rather than a declaration of intent."""
    from maistro.workspaces.pg_store import PgWorkspaceStore
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    scope_store = InMemoryProjectScopeStore()
    implementations = [
        InMemoryWorkspaceStore(project_store=scope_store),
        SqliteWorkspaceStore(None, project_store=scope_store),  # type: ignore[arg-type]
        PgWorkspaceStore(None, project_store=scope_store),  # type: ignore[arg-type]
    ]

    assert [isinstance(store, WorkspaceStore) for store in implementations] == [True] * 3


def test_the_container_requires_the_workspace_tables_of_a_postgres_deployment() -> None:
    """Otherwise a `postgresql://` deployment that skipped `alembic upgrade
    head` learns about it from the fallback warning, in a log, after the fact."""
    from maistro.container import _REQUIRED_PG_TABLES

    assert set(WORKSPACE_PG_TABLES) <= set(_REQUIRED_PG_TABLES)
