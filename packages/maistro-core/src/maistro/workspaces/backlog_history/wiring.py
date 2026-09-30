"""Selecting the BacklogItem history store on the Project store's own backend (#101).

The backend is read from `project_store` — `backend_of`, the helper
`wire_workspace_store` (#516) reads — so an item's history cannot land in a
different database than the item itself. PostgreSQL has no durable history
store yet, so it falls back to in-process with a warning, exactly as the #98
item store does: honest about the loss instead of silently split.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.projects.scope_store import ProjectScopeStore
from maistro.types.errors import ConfigError
from maistro.workspaces.backlog_history.store import (
    BacklogHistoryStore,
    InMemoryBacklogHistoryStore,
)
from maistro.workspaces.wiring import backend_of

logger = logging.getLogger(__name__)


async def wire_backlog_history_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> BacklogHistoryStore:
    """Return the BacklogItem history store for the deployment's Project backend."""
    backend = backend_of(project_store)
    if backend == "postgres":
        del pg_pool  # the PostgreSQL store is a later #101 slice
        logger.warning(
            "Projects are stored in PostgreSQL but the BacklogItem history store has "
            "no PostgreSQL backend yet, so BacklogItem history is in-process and lost "
            "on restart (#101)."
        )
        return InMemoryBacklogHistoryStore()
    if backend == "sqlite":
        if conn is None:
            msg = (
                "Projects are stored in SQLite but no connection reached the BacklogItem "
                "history store, so history would be lost on restart while the items "
                "survive (#101)."
            )
            raise ConfigError(msg)
        from maistro.workspaces.backlog_history.sqlite_store import SqliteBacklogHistoryStore

        store = SqliteBacklogHistoryStore(conn, project_store=project_store)
        await store.ensure_schema()
        return store
    return InMemoryBacklogHistoryStore()


__all__ = ["wire_backlog_history_store"]
