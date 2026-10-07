"""Selecting the BacklogItem work-source store on the Project store's backend (#98).

The store backend is read from `project_store` — `backend_of`, the same helper
`wire_workspace_store` (#516) and `wire_backlog_history_store` (#101) read — so
the work-source cannot land in a different database than the Workspaces it
serves. Unlike the history journal, all three backends exist here: the
PostgreSQL tables ship as Alembic revision ``059_backlog_work_source``, so a
PostgreSQL deployment gets the durable store rather than a fallback.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.backlog.store import BacklogStore, InMemoryBacklogStore
from maistro.projects.scope_store import ProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.wiring import backend_of

logger = logging.getLogger(__name__)


async def wire_backlog_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> BacklogStore:
    """Return the BacklogItem work-source store for the deployment's Project backend."""
    backend = backend_of(project_store)
    if backend == "postgres":
        if pg_pool is None:
            msg = (
                "Projects are stored in PostgreSQL but no pool reached the BacklogItem "
                "work-source store, so items would be lost on restart while the "
                "projects survive (#98)."
            )
            raise ConfigError(msg)
        from maistro.backlog.pg_store import PgBacklogStore

        # No `ensure_schema`: the `backlog_items`/`backlog_claims`/`backlog_events`
        # tables come from Alembic revision 059, like every other PostgreSQL
        # store's tables.
        return PgBacklogStore(pg_pool)
    if backend == "sqlite":
        if conn is None:
            msg = (
                "Projects are stored in SQLite but no connection reached the BacklogItem "
                "work-source store, so items would be lost on restart while the "
                "projects survive (#98)."
            )
            raise ConfigError(msg)
        from maistro.backlog.sqlite_store import SqliteBacklogStore

        store = SqliteBacklogStore(conn)
        await store.ensure_schema()
        return store
    return InMemoryBacklogStore()


__all__ = ["wire_backlog_store"]
