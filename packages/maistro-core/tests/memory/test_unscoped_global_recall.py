"""Project-only recall must not republish org-bound globals (#1247).

`list_by_scope` skips the scope hierarchy when the caller names no agent, user,
team, or org — SPEC-244 project changelog recall. That skip used to return
every row, so a `global` memory bound to an organization was visible to a
caller with no org context. `matches_scope` / `scope_predicate` already refuse
that wildcard; these stores have to apply the same clause on the skip path.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.exposure import MemoryExposureMode
from maistro.persistence.pg_episodic import _scoped_list_query
from maistro.types.memory import EpisodicMemory, MemoryScope

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]


def _memory(memory_id: str, **fields: Any) -> EpisodicMemory:
    fields.setdefault("content", memory_id)
    fields.setdefault("project_id", "proj-1")
    fields.setdefault("weight", 0.9)
    return EpisodicMemory(memory_id=memory_id, **fields)


def _corpus() -> list[EpisodicMemory]:
    return [
        _memory("bound", scope=MemoryScope.GLOBAL, org_id="org-a"),
        _memory("open", scope=MemoryScope.GLOBAL, org_id=""),
        _memory("changelog", scope=MemoryScope.ORGANIZATION, org_id="org-a"),
        _memory("other", scope=MemoryScope.GLOBAL, org_id="org-b"),
    ]


async def test_unscoped_recall_hides_org_bound_globals() -> None:
    """A caller with no org sees unbound globals and project rows, not org-bound globals."""
    volatile = InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    for memory in _corpus():
        await volatile.store(memory)

    unscoped = {memory.memory_id for memory in await volatile.list_by_scope(project_id="proj-1")}
    assert unscoped == {"open", "changelog"}

    scoped = {
        memory.memory_id
        for memory in await volatile.list_by_scope(org_id="org-a", project_id="proj-1")
    }
    assert "bound" in scoped
    assert "other" not in scoped
    assert "open" in scoped

    conn = await aiosqlite.connect(":memory:")
    try:
        from maistro.persistence.sqlite_episodic import SqliteEpisodicStore

        durable = SqliteEpisodicStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await durable.ensure_schema()
        for memory in _corpus():
            await durable.store(memory)
        durable_ids = {
            memory.memory_id for memory in await durable.list_by_scope(project_id="proj-1")
        }
        assert durable_ids == {"open", "changelog"}
        durable_scoped = {
            memory.memory_id
            for memory in await durable.list_by_scope(org_id="org-a", project_id="proj-1")
        }
        assert "bound" in durable_scoped
        assert "other" not in durable_scoped
    finally:
        await conn.close()

    sql, params = _scoped_list_query(
        agent_id=None,
        user_id=None,
        team_id=None,
        org_id=None,
        project_id="proj-1",
        min_weight=0.0,
        limit=50,
    )
    assert "scope != 'global' OR (scope = 'global' AND org_id = '')" in sql
    assert params == [0.0, "proj-1", 50]

    scoped_sql, scoped_params = _scoped_list_query(
        agent_id=None,
        user_id=None,
        team_id=None,
        org_id="org-a",
        project_id=None,
        min_weight=0.0,
        limit=50,
    )
    assert "scope != 'global' OR" not in scoped_sql
    assert "org-a" in scoped_params
