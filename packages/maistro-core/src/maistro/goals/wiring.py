"""Selecting the Goal store on the Project scope store's own backend (#1572).

Goals reference Projects by foreign key, so the backend is read from the
Project scope store the spine already selected, as `wire_workspace_store`
does, rather than probed again. A deployment that cannot honour that backend
is refused rather than given in-process Goals beside durable Projects: the
fallback #516 retired for Workspaces, for the same reason.
"""

from __future__ import annotations

from typing import Any, Final

from maistro.goals.store import GoalStore, InMemoryGoalStore
from maistro.projects.scope_store import ProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.wiring import _backend_of

#: Tables `alembic/versions/041_goals.py` owns.
GOAL_PG_TABLES: Final = ("goals", "goal_revisions")


async def _missing_goal_tables(pg_pool: Any) -> list[str]:
    return [
        table
        for table in GOAL_PG_TABLES
        if not await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]


async def wire_goal_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> GoalStore:
    backend = _backend_of(project_store)
    if backend == "postgres":
        missing = ["a pool"] if pg_pool is None else await _missing_goal_tables(pg_pool)
        if pg_pool is None or missing:
            msg = (
                "Projects are stored in PostgreSQL but the Goal store is missing "
                f"{', '.join(missing)}, so Goals would be in-process and lost on restart. "
                "Run `alembic upgrade head` against the Project database (#1572)."
            )
            raise ConfigError(msg)
        from maistro.goals.pg_store import PgGoalStore

        return PgGoalStore(pg_pool)
    if backend == "sqlite":
        if conn is None:
            msg = (
                "Projects are stored in SQLite but no connection reached the Goal store, "
                "so Goals would be in-process and lost on restart (#1572)."
            )
            raise ConfigError(msg)
        from maistro.goals.sqlite_store import SqliteGoalStore

        store = SqliteGoalStore(conn, project_store=project_store)
        await store.ensure_schema()
        return store
    return InMemoryGoalStore(project_store=project_store)


__all__ = ["GOAL_PG_TABLES", "wire_goal_store"]
