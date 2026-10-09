"""Selecting the Goal store the deployment actually has (#1572).

Follows the campaigns rule: the store rides the database the deployment
already selected, and a deployment that cannot honour durability is told so
loudly instead of silently losing canonical Goals on restart. A PostgreSQL
pool always selects the durable ``PgGoalStore`` — never an in-process store
that only looks the same, which is the split-backend defect
``workspaces/wiring.py`` documents. When the pool's database has not run
`alembic upgrade head` yet, the missing migration-062 tables are created here
(``ensure_goal_schema``, the same contract the event stores ship: wiring
creates the schema it needs) rather than refusing a Container startup over
tables one idempotent statement away; managed deployments keep getting the
tables from the migration. SQLite selects its twin over the same aiosqlite
pool the rest of the SQLite backend uses and creates its tables the same way;
no database at all selects the in-memory reference with a warning naming the
cost.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.goals.pg_store import GOAL_PG_TABLES
from maistro.goals.store import GoalStore, InMemoryGoalStore

logger = logging.getLogger(__name__)

# `GOAL_PG_TABLES` is re-exported from ``pg_store``, next to the DDL that
# creates those tables and the migration that owns them for managed
# deployments.


async def wire_goal_store(
    conn: Any,
    *,
    pg_pool: Any = None,
) -> GoalStore:
    """Return the Goal store on the deployment's selected database backend.

    ``conn`` is the aiosqlite pool the SQLite tier shares, ``pg_pool`` the
    asyncpg pool when the deployment selected PostgreSQL. A supplied pool
    always selects PostgreSQL; a database missing the Goal tables gets them
    created at wiring rather than a startup refusal or a split to a second
    backend. Only deployments without a PostgreSQL pool may select SQLite or
    memory.
    """
    if pg_pool is not None:
        from maistro.goals.pg_store import PgGoalStore, ensure_goal_schema

        await ensure_goal_schema(pg_pool)
        return PgGoalStore(pg_pool)
    if conn is not None:
        from maistro.goals.sqlite_store import SqliteGoalStore

        store = SqliteGoalStore(conn)
        await store.ensure_schema()
        return store
    logger.warning(
        "No database is available, so canonical Goals are in-process and lost on "
        "restart. Run with a database URL so Goals persist (#1572)."
    )
    return InMemoryGoalStore()


__all__ = ["GOAL_PG_TABLES", "wire_goal_store"]
