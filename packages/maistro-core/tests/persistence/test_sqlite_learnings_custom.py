"""Lane-reproduction tests for #1156: source_query and team_id on SQLite.

These mirror the dedicated conformance nodes in test_backend_conformance.py
but pin the exact reproduction from the audit: a stored learning's
`source_query` and `team_id` must survive the SQLite round trip and scope
`find_relevant` reads, exactly as the PostgreSQL twin does.
"""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import Learning


@pytest.fixture
async def store():
    conn = await aiosqlite.connect(":memory:")
    s = SqliteLearningStore(conn)
    await s.ensure_schema()
    yield s
    await conn.close()


def make_learning(**kwargs: object) -> Learning:
    defaults: dict[str, object] = {
        "category": "tooling",
        "trigger_keys": ["foo", "bar"],
        "learning": "use the right flag",
        "tool_name": "bash",
        "user_id": "u1",
    }
    defaults.update(kwargs)
    return Learning(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_store_persists_source_query_and_team_id(store: SqliteLearningStore) -> None:
    lid = await store.store(make_learning(source_query="SELECT * FROM users", team_id="team-123"))
    assert lid > 0
    all_learnings = await store.list_all(org_id="")
    learning = all_learnings[0]
    assert learning.source_query == "SELECT * FROM users"
    assert learning.team_id == "team-123"


@pytest.mark.asyncio
async def test_find_relevant_filters_by_team_id(store: SqliteLearningStore) -> None:
    await store.store(make_learning(team_id="team-123", trigger_keys=["foo"]))
    await store.store(make_learning(team_id="team-456", trigger_keys=["foo"]))

    results = await store.find_relevant("foo", org_id="", team_id="team-123")
    assert len(results) == 1
    assert results[0].team_id == "team-123"


@pytest.mark.asyncio
async def test_round_trip_source_query_and_team_id(store: SqliteLearningStore) -> None:
    """A team-scoped read that matches a trigger key returns the stored
    provenance fields intact. `find_relevant` scores trigger keys, so the
    query text must contain one; `source_query` is carried, not matched."""
    l1 = make_learning(source_query="SELECT 1", team_id="t1", org_id="o1")
    await store.store(l1)

    results = await store.find_relevant("please use foo", org_id="o1", team_id="t1")
    assert len(results) == 1
    assert results[0].source_query == "SELECT 1"
    assert results[0].team_id == "t1"
    assert results[0].org_id == "o1"
