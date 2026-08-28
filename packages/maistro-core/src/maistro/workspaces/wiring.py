"""Selecting the Workspace store the deployment actually has (#516).

Separate from `wire_execution_spine` rather than another element of its tuple,
for the reason `wire_chat_admission` is separate: adding a return value to that
function changes every call site that unpacks it, and there are a dozen. This
takes the Project scope store that one already selected, so the two cannot end
up in different databases — which is the failure the "same backend decision"
requirement is really about. A Workspace whose Root Project lives somewhere
else is a Workspace whose Runs cannot be filed.

That sentence was true of the intent and false of the code (Codex, #516). The
Workspace backend was chosen by an *independent* probe of `pg_pool` for the
019 tables, so a caller-supplied pool holding only the spine tables selected
PostgreSQL Projects and fell through to SQLite Workspaces, and a pool holding
only the Workspace tables produced the inverse. Both split a Workspace from its
own Root Project across two databases, which is exactly what the docstring
promised could not happen.

The backend is now read from `project_store` itself, which *is* the selected
backend, and a deployment that cannot honour it is refused rather than split.
Refusing is the harder behaviour and the correct one: a split pair is not
recoverable by restarting with the right configuration, because the rows are
already in two places.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from maistro.projects.scope_store import ProjectScopeStore
from maistro.types.errors import ConfigError
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


def _backend_of(project_store: ProjectScopeStore) -> str:
    """Which relational backend the Project scope store already committed to.

    Read from the object rather than re-derived from configuration: the store
    is the decision. Matched on the class name so that neither PostgreSQL nor
    aiosqlite has to be importable to ask the question — this runs during
    container construction, where the unselected backend's driver may be
    absent.
    """
    name = type(project_store).__name__
    if name.startswith("Pg"):
        return "postgres"
    if name.startswith("Sqlite"):
        return "sqlite"
    return "memory"


async def wire_workspace_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> WorkspaceStore:
    """Return the Workspace store on the Project store's own backend.

    `project_store` is passed rather than resolved: it is the store the
    Workspace's Root Project is created in, and every implementation provisions
    that Root Project as part of `create`.
    """
    backend = _backend_of(project_store)

    if backend == "postgres":
        if pg_pool is None:
            msg = (
                "Projects are stored in PostgreSQL but no pool reached the Workspace "
                "store, so Workspaces would persist somewhere else. Pass the same pool "
                "the Project scope store uses (#516)."
            )
            raise ConfigError(msg)
        if not await _workspaces_are_migrated(pg_pool):
            msg = (
                "Projects are stored in PostgreSQL but this database is missing the "
                "canonical Workspace tables, so a Workspace and its Root Project would "
                "land in different databases. Run `alembic upgrade head` against it "
                "(#516)."
            )
            raise ConfigError(msg)
        # No ensure_schema: these tables come from `alembic/versions/019`. A
        # store that quietly created its own would be a second schema owner and
        # a second thing to keep in step — the defect migration 003 left behind
        # and #178 had to undo.
        from maistro.workspaces.pg_store import PgWorkspaceStore

        return PgWorkspaceStore(pg_pool, project_store=project_store)

    if backend == "sqlite":
        if conn is None:
            msg = (
                "Projects are stored in SQLite but no connection reached the Workspace "
                "store, so Workspaces would be in-process and lost on restart while "
                "their Root Projects survive (#516)."
            )
            raise ConfigError(msg)
        from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

        sqlite_store = SqliteWorkspaceStore(conn, project_store=project_store)
        await sqlite_store.ensure_schema()
        return sqlite_store

    from maistro.workspaces.store import InMemoryWorkspaceStore

    return InMemoryWorkspaceStore(project_store=project_store)


__all__ = ["WORKSPACE_PG_TABLES", "wire_workspace_store"]
