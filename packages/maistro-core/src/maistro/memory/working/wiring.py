"""Selecting the working-memory log the deployment actually has.

Follows the same rule as `maistro.workspaces.campaigns.wiring` and
`maistro.goals.wiring`: the durable log rides the backend the deployment
already selected, and a deployment that cannot honour durability is told so
loudly instead of silently keeping its "lossless" observation log in process
memory (#301). A PostgreSQL pool selects the durable ``PgWorkspaceLogStore``
— never the in-process store that merely looks the same, which is exactly the
split this wiring shipped before the PG twin existed: the container passed
only the SQLite pool here, so a ``postgresql://`` deployment answered with
the process-memory log and #105's retained-observation requirement was
unreachable on its own selected backend. When the pool's database has not run
`alembic upgrade head` yet, the missing migration-072 tables are created here
(``ensure_working_log_schema``, the same "wiring creates the schema it needs"
contract the Goal and event stores ship) rather than refusing Container
startup over tables one idempotent statement away. SQLite selects its twin
over the same aiosqlite pool the rest of the SQLite backend uses; no database
at all selects the in-memory reference with a warning naming the cost.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.memory.working.pg_store import WORKING_LOG_PG_TABLES
from maistro.memory.working.projection import WorkingMemoryManager
from maistro.memory.working.store import InMemoryWorkspaceLogStore

logger = logging.getLogger(__name__)

# `WORKING_LOG_PG_TABLES` is re-exported from ``pg_store``, next to the DDL
# that creates those tables and the migration that owns them for managed
# deployments.

__all__ = [
    "WORKING_LOG_PG_TABLES",
    "wire_in_memory_working_memory",
    "wire_working_memory",
]


async def wire_working_memory(db_pool: Any, *, pg_pool: Any = None) -> WorkingMemoryManager:
    """Wire working memory over the deployment's selected database backend.

    A supplied ``pg_pool`` always selects PostgreSQL — the durable twin whose
    tables migration 072 owns for managed deployments and
    ``ensure_working_log_schema`` creates here otherwise — so a
    ``postgresql://`` deployment's observation log and its addressable
    results live beside the Workspaces they belong to and outlive the
    process (#105). ``db_pool`` is the aiosqlite pool the rest of the SQLite
    backend uses; only a deployment without a PostgreSQL pool may select it
    or the in-memory fallback."""
    if pg_pool is not None:
        from maistro.memory.working.pg_store import (
            PgWorkspaceLogStore,
            ensure_working_log_schema,
        )

        await ensure_working_log_schema(pg_pool)
        return WorkingMemoryManager(PgWorkspaceLogStore(pg_pool))
    if db_pool is not None:
        from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

        store = SqliteWorkspaceLogStore(db_pool)
        await store.ensure_schema()
        return WorkingMemoryManager(store)
    return wire_in_memory_working_memory()


def wire_in_memory_working_memory(*, warn: bool = True) -> WorkingMemoryManager:
    """The non-durable fallback. ``warn`` keeps the loss loud: observations
    and full results written through this manager are lost on restart, which
    is exactly what the durable log exists to prevent for real deployments."""
    if warn:
        logger.warning(
            "No SQLite database pool is available, so the workspace observation "
            "log is in-process and working memory is lost on restart. Run with a "
            "sqlite database URL so log-as-context persists (#301)."
        )
    return WorkingMemoryManager(InMemoryWorkspaceLogStore())
