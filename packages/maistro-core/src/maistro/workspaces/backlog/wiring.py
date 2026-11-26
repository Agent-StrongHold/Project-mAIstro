"""Selecting the BacklogItem store on the Project store's own backend (#98).

The backend is read from `project_store`, as `wire_workspace_store` does, so
an item and the Project it is filed in cannot land in different databases.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.projects.scope_store import ProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.backlog.store import BacklogItemStore, InMemoryBacklogItemStore
from maistro.workspaces.wiring import backend_of

logger = logging.getLogger(__name__)


async def wire_backlog_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> BacklogItemStore:
    """Return the BacklogItem store for the deployment's Project backend."""
    backend = backend_of(project_store)
    if backend == "postgres":
        del pg_pool  # the PostgreSQL store is a later #98 slice
        logger.warning(
            "Projects are stored in PostgreSQL but the BacklogItem store has no "
            "PostgreSQL backend yet, so BacklogItems are in-process and lost on "
            "restart (#98)."
        )
        return InMemoryBacklogItemStore(project_store=project_store)
    if backend == "sqlite":
        if conn is None:
            msg = (
                "Projects are stored in SQLite but no connection reached the "
                "BacklogItem store, so BacklogItems would be lost on restart while "
                "their Projects survive (#98)."
            )
            raise ConfigError(msg)
        from maistro.workspaces.backlog.sqlite_store import SqliteBacklogItemStore

        store = SqliteBacklogItemStore(conn, project_store=project_store)
        await store.ensure_schema()
        return store
    return InMemoryBacklogItemStore(project_store=project_store)


__all__ = ["wire_backlog_store"]
