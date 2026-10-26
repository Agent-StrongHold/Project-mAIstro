"""Which BacklogItem store each Project backend yields (#98)."""

from __future__ import annotations

import logging

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.backlog import InMemoryBacklogItemStore
from maistro.workspaces.backlog.wiring import wire_backlog_store


async def test_postgres_projects_fall_back_to_memory_with_a_warning(caplog) -> None:
    """No PostgreSQL BacklogItem store exists yet; the fallback must say so."""
    from maistro.projects.pg_scope_store import PgProjectScopeStore

    project_store = PgProjectScopeStore(object())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="maistro.workspaces.backlog.wiring"):
        store = await wire_backlog_store(None, project_store=project_store, pg_pool=object())

    assert isinstance(store, InMemoryBacklogItemStore)
    assert "lost on restart" in caplog.text


async def test_sqlite_projects_without_a_connection_are_refused(tmp_path) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

    conn = await aiosqlite.connect(tmp_path / "x.db")
    try:
        with pytest.raises(ConfigError):
            await wire_backlog_store(None, project_store=SqliteProjectScopeStore(conn))
    finally:
        await conn.close()


async def test_sqlite_store_refuses_a_project_store_without_a_transaction(tmp_path) -> None:
    import aiosqlite

    from maistro.workspaces.backlog.sqlite_store import SqliteBacklogItemStore

    conn = await aiosqlite.connect(tmp_path / "x.db")
    try:
        with pytest.raises(TypeError):
            SqliteBacklogItemStore(conn, project_store=InMemoryProjectScopeStore())
    finally:
        await conn.close()
