"""Select the live Persona store on the same backend as canonical ownership."""

from __future__ import annotations

import logging
from typing import Any, Final

from maistro.projects.scope_store import ProjectScopeStore
from maistro.types.errors import ConfigError

from .store import PersonaStore

logger = logging.getLogger(__name__)
PERSONA_PG_TABLES: Final = ("canonical_personas",)


def _backend_of(project_store: ProjectScopeStore) -> str:
    name = type(project_store).__name__
    if name.startswith("Pg"):
        return "postgres"
    if name.startswith("Sqlite"):
        return "sqlite"
    return "memory"


async def _personas_are_migrated(pg_pool: Any) -> bool:
    missing = [
        table
        for table in PERSONA_PG_TABLES
        if not await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]
    if not missing:
        return True
    logger.warning(
        "PostgreSQL is missing canonical Persona tables (%s); run `alembic upgrade head`.",
        ", ".join(missing),
    )
    return False


async def wire_persona_store(
    conn: Any,
    *,
    project_store: ProjectScopeStore,
    pg_pool: Any = None,
) -> PersonaStore:
    """Return the live Persona store beside the selected Project store.

    A durable Project tree with an in-memory Persona would split one Workspace's
    canonical ownership across backends, so missing matching durability is a
    configuration error rather than a silent fallback.
    """

    backend = _backend_of(project_store)
    if backend == "postgres":
        if pg_pool is None:
            raise ConfigError(
                "Projects are stored in PostgreSQL but no pool reached the Persona store"
            )
        if not await _personas_are_migrated(pg_pool):
            raise ConfigError(
                "Projects are stored in PostgreSQL but canonical Persona tables are missing; "
                "run `alembic upgrade head`"
            )
        from .pg_store import PgPersonaStore

        return PgPersonaStore(pg_pool)

    if backend == "sqlite":
        if conn is None:
            raise ConfigError(
                "Projects are stored in SQLite but no connection reached the Persona store"
            )
        from .sqlite_store import SqlitePersonaStore

        store = SqlitePersonaStore(conn)
        await store.ensure_schema()
        return store

    from .store import InMemoryPersonaStore

    return InMemoryPersonaStore()


__all__ = ["PERSONA_PG_TABLES", "wire_persona_store"]
