"""Selecting the Goal store the deployment actually has (#1572).

Follows the campaigns rule: the store rides the database the deployment
already selected, and a deployment that cannot honour durability is told so
loudly instead of silently losing canonical Goals on restart. A PostgreSQL
pool selects the durable ``PgGoalStore`` **only** when the migration-062
tables are present — a pool that has not run `alembic upgrade head` must not
be answered with an in-process store that only looks the same, which is the
split-backend defect `workspaces/wiring.py` documents. SQLite selects its twin
over the same aiosqlite pool the rest of the SQLite backend uses; no database
at all selects the in-memory reference with a warning naming the cost.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from maistro.goals.store import GoalStore, InMemoryGoalStore
from maistro.types.errors import ConfigError

logger = logging.getLogger(__name__)

#: Tables the PostgreSQL Goal store needs before it may be selected.
#: Migration `062_canonical_goals` owns them.
GOAL_PG_TABLES: Final = (
    "canonical_goals",
    "canonical_goal_revisions",
    "canonical_goal_transitions",
)


async def _require_goal_schema(pg_pool: Any) -> None:
    missing = [
        table
        for table in GOAL_PG_TABLES
        if not await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]
    if missing:
        msg = (
            f"PostgreSQL pool is missing the canonical Goal tables ({', '.join(missing)}). "
            "Refusing to store Goals on a different backend. Run `alembic upgrade head` "
            "against this database before starting the Container (#1572)."
        )
        raise ConfigError(msg)


async def wire_goal_store(
    conn: Any,
    *,
    pg_pool: Any = None,
) -> GoalStore:
    """Return the Goal store on the deployment's selected database backend.

    ``conn`` is the aiosqlite pool the SQLite tier shares, ``pg_pool`` the
    asyncpg pool when the deployment selected PostgreSQL. A supplied pool
    always selects PostgreSQL; missing Goal tables refuse startup rather than
    splitting Goals from the deployment's durable Workspace/Run authority.
    Only deployments without a PostgreSQL pool may select SQLite or memory.
    """
    if pg_pool is not None:
        from maistro.goals.pg_store import PgGoalStore

        await _require_goal_schema(pg_pool)
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
