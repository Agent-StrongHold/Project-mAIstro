"""Plan regression for the SQLite recovery index (#1151 review)."""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.sqlite_store import SqliteRunStore


@pytest.mark.asyncio
async def test_list_by_status_reads_the_index_without_a_sort() -> None:
    """`idx_canonical_runs_status` carries the `list_by_status` ordering, so a
    bounded recovery page walks the index in `(created_at, run_id)` order
    rather than building a temporary B-tree over the whole live population."""
    conn = await aiosqlite.connect(":memory:")
    store = SqliteRunStore(conn, project_store=InMemoryProjectScopeStore())
    try:
        await store.ensure_schema()
        cursor = await store._conn.execute(
            "EXPLAIN QUERY PLAN SELECT payload FROM canonical_runs "
            "WHERE status = ? "
            "ORDER BY json_extract(payload, '$.created_at'), run_id "
            "LIMIT ? OFFSET ?",
            (RunStatus.RUNNING.value, 100, 0),
        )
        plan = " ".join(str(row[3]) for row in await cursor.fetchall())
    finally:
        await conn.close()

    assert "idx_canonical_runs_status" in plan
    assert "TEMP B-TREE" not in plan
