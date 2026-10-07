"""Backend selection for the BacklogItem work-source store (#98 wiring).

`wire_backlog_store` reads the Project store's backend, so the work-source
cannot land in a different database than the Workspaces it serves: PostgreSQL
gets the durable store over Alembic revision 059's tables, SQLite gets the
durable twin on its own connection, and anything else gets the in-memory
reference. A backend that arrives without its driver handle is a wiring bug
and must refuse loudly rather than silently demote the deployment.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import aiosqlite
import pytest

from maistro.backlog.pg_store import PgBacklogStore
from maistro.backlog.sqlite_store import SqliteBacklogStore
from maistro.backlog.store import InMemoryBacklogStore
from maistro.backlog.wiring import wire_backlog_store
from maistro.types.errors import ConfigError
from maistro.workspaces.wiring import backend_of


class PgProjectScopeStoreStub:
    """`backend_of` matches on the class-name prefix, like the real store."""


class SqliteProjectScopeStoreStub:
    """`backend_of` matches on the class-name prefix, like the real store."""


def _project_store(backend: str) -> Any:
    return {
        "postgres": PgProjectScopeStoreStub(),
        "sqlite": SqliteProjectScopeStoreStub(),
        "memory": SimpleNamespace(),
    }[backend]


async def test_backend_selection_follows_the_project_store() -> None:
    assert backend_of(_project_store("postgres")) == "postgres"
    assert backend_of(_project_store("sqlite")) == "sqlite"
    assert backend_of(_project_store("memory")) == "memory"


async def test_postgres_selects_the_durable_store_over_its_pool() -> None:
    store = await wire_backlog_store(
        None, project_store=_project_store("postgres"), pg_pool=object()
    )
    assert isinstance(store, PgBacklogStore)


async def test_postgres_without_a_pool_is_a_wiring_error() -> None:
    with pytest.raises(ConfigError, match="no pool reached"):
        await wire_backlog_store(None, project_store=_project_store("postgres"))


async def test_sqlite_selects_the_durable_twin_and_ensures_its_schema() -> None:
    async with aiosqlite.connect(":memory:") as conn:
        store = await wire_backlog_store(conn, project_store=_project_store("sqlite"))
        assert isinstance(store, SqliteBacklogStore)

        # The schema was ensured, so the store works immediately: one item
        # round-trips with its provenance event.
        item = await store.create_item(workspace_id="ws-1", title="Wired", actor="wiring-test")
        fetched = await store.get_item(item.item_id)
        assert fetched is not None and fetched.title == "Wired"
        assert [event.kind for event in await store.events(item.item_id)] == ["created"]


async def test_sqlite_without_a_connection_is_a_wiring_error() -> None:
    with pytest.raises(ConfigError, match="no connection reached"):
        await wire_backlog_store(None, project_store=_project_store("sqlite"))


async def test_memory_backend_gets_the_reference_store() -> None:
    store = await wire_backlog_store(None, project_store=_project_store("memory"), pg_pool=None)
    assert isinstance(store, InMemoryBacklogStore)
