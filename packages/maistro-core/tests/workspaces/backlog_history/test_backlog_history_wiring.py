"""Which BacklogItem history store each backend actually yields (#101).

Same discipline as `workspaces/test_wiring.py` (#516): the selection is
asserted, not assumed, and each backend is exercised against its own Project
store — history filed anywhere but the Project store's database is provenance
that dies on restart.
"""

from __future__ import annotations

import logging

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.backlog_history.store import InMemoryBacklogHistoryStore
from maistro.workspaces.backlog_history.wiring import wire_backlog_history_store
from maistro.workspaces.wiring import backend_of


async def test_no_backend_yields_the_in_memory_reference() -> None:
    store = await wire_backlog_history_store(None, project_store=InMemoryProjectScopeStore())
    assert isinstance(store, InMemoryBacklogHistoryStore)


async def test_a_sqlite_project_store_yields_the_sqlite_journal(tmp_path) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.workspaces.backlog_history.sqlite_store import SqliteBacklogHistoryStore

    conn = await aiosqlite.connect(tmp_path / "wired.db")
    try:
        project_store = SqliteProjectScopeStore(conn)
        await project_store.ensure_schema()
        store = await wire_backlog_history_store(conn, project_store=project_store)

        assert isinstance(store, SqliteBacklogHistoryStore)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workspace_backlog_history'"
        ) as cursor:
            assert await cursor.fetchone() is not None
    finally:
        await conn.close()


async def test_sqlite_without_a_connection_is_refused_not_split(tmp_path) -> None:
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

    conn = await aiosqlite.connect(tmp_path / "wired.db")
    try:
        project_store = SqliteProjectScopeStore(conn)
        await project_store.ensure_schema()
        with pytest.raises(ConfigError, match="no connection reached"):
            await wire_backlog_history_store(None, project_store=project_store)
    finally:
        await conn.close()


async def test_a_postgres_project_store_falls_back_loudly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from maistro.projects.pg_scope_store import PgProjectScopeStore

    class _FakePool:
        async def fetchval(self, *_args: object, **_kwargs: object) -> bool:
            return True

    # Named so `backend_of`'s class-name check reads it as the PostgreSQL
    # backend without constructing a real pool-backed store.
    class PgFakeProjectScopeStore(PgProjectScopeStore):
        def __init__(self) -> None:  # pragma: no cover - never touched
            raise AssertionError("the backend check must be by name, not construction")

    store = await wire_backlog_history_store(
        None,
        project_store=PgFakeProjectScopeStore.__new__(PgFakeProjectScopeStore),
        pg_pool=_FakePool(),
    )
    assert isinstance(store, InMemoryBacklogHistoryStore)
    assert any("no PostgreSQL backend yet" in record.message for record in caplog.records)


async def test_sqlite_store_refuses_a_project_store_without_a_transaction(tmp_path) -> None:
    import aiosqlite

    from maistro.workspaces.backlog_history.sqlite_store import SqliteBacklogHistoryStore

    conn = await aiosqlite.connect(tmp_path / "wired.db")
    try:
        with pytest.raises(TypeError, match="transaction"):
            SqliteBacklogHistoryStore(conn, project_store=InMemoryProjectScopeStore())
    finally:
        await conn.close()


async def test_backend_of_reads_the_project_store_decision() -> None:
    """The public helper both wirings share; renaming it private again would
    push this module back to re-deriving the backend by class-name probing."""
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

    assert backend_of(InMemoryProjectScopeStore()) == "memory"
    conn = await aiosqlite.connect(":memory:")
    try:
        assert backend_of(SqliteProjectScopeStore(conn)) == "sqlite"
    finally:
        await conn.close()


async def test_the_container_wires_history_on_the_project_store_backend(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from maistro.container import create_container
    from maistro.types.config import AgentConfig
    from maistro.workspaces.backlog_history.sqlite_store import SqliteBacklogHistoryStore

    monkeypatch.setenv("MAISTRO_ROUTER_API_KEY", "test-key")
    container = await create_container(AgentConfig(router_api_key="test-key"))  # type: ignore[arg-type]
    assert type(container.backlog_history_store).__name__ == "InMemoryBacklogHistoryStore"

    with caplog.at_level(logging.WARNING):
        container = await create_container(
            AgentConfig(router_api_key="test-key", database_url="sqlite://")  # type: ignore[arg-type]
        )
    assert isinstance(container.backlog_history_store, SqliteBacklogHistoryStore)
