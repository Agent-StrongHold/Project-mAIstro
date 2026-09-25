"""Which Goal store each Project backend yields, and which pairings are refused (#1572)."""

from __future__ import annotations

import pytest

from maistro.goals.store import InMemoryGoalStore
from maistro.goals.wiring import GOAL_PG_TABLES, wire_goal_store
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.types.errors import ConfigError


def _pg_projects():
    """The real class: the selector reads its name, and `__init__` does no I/O."""
    from maistro.projects.pg_scope_store import PgProjectScopeStore

    return PgProjectScopeStore(None)  # type: ignore[arg-type]


class _Pool:
    def __init__(self, *, migrated: bool) -> None:
        self.migrated = migrated
        self.asked: list[str] = []

    async def fetchval(self, _query: str, argument: str) -> bool:
        self.asked.append(argument)
        return self.migrated


async def test_in_memory_projects_yield_the_reference() -> None:
    store = await wire_goal_store(None, project_store=InMemoryProjectScopeStore())

    assert isinstance(store, InMemoryGoalStore)


async def test_a_migrated_postgres_pool_yields_the_postgres_store() -> None:
    from maistro.goals.pg_store import PgGoalStore

    pool = _Pool(migrated=True)

    store = await wire_goal_store(None, project_store=_pg_projects(), pg_pool=pool)

    assert isinstance(store, PgGoalStore)
    assert pool.asked == [f"public.{table}" for table in GOAL_PG_TABLES]


async def test_an_unmigrated_postgres_pool_is_refused_rather_than_split() -> None:
    with pytest.raises(ConfigError, match="goals, goal_revisions"):
        await wire_goal_store(None, project_store=_pg_projects(), pg_pool=_Pool(migrated=False))


async def test_postgres_projects_without_a_pool_are_refused() -> None:
    with pytest.raises(ConfigError, match="alembic upgrade head"):
        await wire_goal_store(None, project_store=_pg_projects())


async def test_sqlite_projects_without_a_connection_are_refused() -> None:
    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

    with pytest.raises(ConfigError, match="no connection reached"):
        await wire_goal_store(None, project_store=SqliteProjectScopeStore(None))  # type: ignore[arg-type]


async def test_the_sqlite_store_refuses_a_project_store_it_cannot_share_a_transaction_with() -> (
    None
):
    from maistro.goals.sqlite_store import SqliteGoalStore

    with pytest.raises(TypeError, match="SqliteProjectScopeStore"):
        SqliteGoalStore(None, project_store=InMemoryProjectScopeStore())  # type: ignore[arg-type]
