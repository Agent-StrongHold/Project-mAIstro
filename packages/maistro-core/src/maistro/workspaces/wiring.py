"""Selecting the Workspace store the deployment actually has (#516).

Separate from `wire_execution_spine` rather than another element of its tuple,
for the reason `wire_chat_admission` is separate: adding a return value to that
function changes every call site that unpacks it, and there are a dozen. This
takes the Project scope store that one already selected, so the two cannot end
up in different databases — which is the failure the "same backend decision"
requirement is really about. A Workspace whose Root Project lives somewhere
else is a Workspace whose Runs cannot be filed.

Backend order is the one every other store follows: PostgreSQL when the
deployment has one and it is migrated, SQLite for a homelab, in-memory
otherwise. The PostgreSQL probe exists for the same reason
`_spine_is_migrated`'s does — a caller-supplied pool has been through no
startup preflight and may legitimately hold only the tables that caller cared
about — and it warns rather than falling back silently, because a durable pool
that ends up with in-memory Workspaces is the shape of #122 and saying so is
the whole difference.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces.store import WorkspaceStore

logger = logging.getLogger(__name__)

#: Tables the PostgreSQL Workspace store needs before it may be selected.
#: Migration `019_canonical_workspaces` owns them.
WORKSPACE_PG_TABLES: Final = (
    "canonical_workspaces",
    "canonical_workspace_memberships",
)


async def _workspaces_are_migrated(pg_pool: Any) -> bool:
    missing = [
        table
        for table in WORKSPACE_PG_TABLES
        if not await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]
    if not missing:
        return True
    logger.warning(
        "PostgreSQL pool is missing the canonical Workspace tables (%s), so Workspaces "
        "are in-process and lost on restart. Run `alembic upgrade head` against this "
        "database to make them durable (#516).",
        ", ".join(missing),
    )
    return False


async def wire_workspace_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> WorkspaceStore:
    """Return the Workspace store matching the selected relational backend.

    `project_store` is passed rather than resolved: it is the store the
    Workspace's Root Project is created in, and every implementation provisions
    that Root Project as part of `create`.
    """
    if pg_pool is not None and await _workspaces_are_migrated(pg_pool):
        # No ensure_schema: these tables come from `alembic/versions/019`. A
        # store that quietly created its own would be a second schema owner and
        # a second thing to keep in step — the defect migration 003 left behind
        # and #178 had to undo.
        from maistro.workspaces.pg_store import PgWorkspaceStore

        return PgWorkspaceStore(pg_pool, project_store=project_store)

    if conn is not None:
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        sqlite_store = SqliteWorkspaceStore(conn, project_store=project_store)
        await sqlite_store.ensure_schema()
        return sqlite_store

    from maistro.workspaces.store import InMemoryWorkspaceStore

    return InMemoryWorkspaceStore(project_store=project_store)


__all__ = ["WORKSPACE_PG_TABLES", "wire_workspace_store"]
