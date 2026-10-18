"""Selecting the working-memory log the deployment actually has.

Follows the same rule as `maistro.workspaces.campaigns.wiring`: the durable
log rides the backend the deployment already selected, and a deployment that
cannot honour durability is told so loudly instead of silently keeping its
"lossless" observation log in process memory (#301). The in-process fallback
is honest for tests and single-turn demos — ADR-082226-5104 §6's projection
discipline still holds — but a log that dies with the process is not the
durable context the epic asks for, so the warning names the cost.

PostgreSQL working-log tables are not part of the schema yet; a PostgreSQL
deployment gets the same fallback campaigns get. The `WorkspaceLogStore`
protocol is the seam a `PgWorkspaceLogStore` would land behind.
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.memory.working.projection import WorkingMemoryManager
from maistro.memory.working.store import InMemoryWorkspaceLogStore

logger = logging.getLogger(__name__)


async def wire_working_memory(db_pool: Any) -> WorkingMemoryManager:
    """Wire working memory over the SQLite database pool.

    ``db_pool`` is the same aiosqlite pool the rest of the SQLite backend
    uses, so the observation log and its addressable results live beside the
    Workspaces they belong to, and a restart re-hydrates the working set the
    last reset left behind."""
    from maistro.memory.working.sqlite_store import SqliteWorkspaceLogStore

    store = SqliteWorkspaceLogStore(db_pool)
    await store.ensure_schema()
    return WorkingMemoryManager(store)


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
