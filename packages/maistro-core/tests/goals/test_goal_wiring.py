"""The Goal store is wired, selected by backend, and exposed by the shipped
Container (#1572).

"Composed in production rather than only in tests" is the acceptance criterion
the store cannot prove about itself: a `goal_store` field nothing constructs is
a library, not composition. So this file proves three claims:

* **Backend selection** — `wire_goal_store` picks the durable twin over the
  SQLite pool the deployment already has, the PostgreSQL store over a pool
  whose migration-058 tables exist, and refuses to answer an *unmigrated*
  PostgreSQL pool with an in-process store that merely looks the same (the
  split-backend defect the Workspace wiring documents). No database at all
  means the in-memory reference — loudly, since canonical Goals that die with
  the process are not canonical.
* **Container exposure** — `create_container` (the one composition Hive's
  adapter and maistro-server's main() both call) exposes `goal_store` and the
  authorized `goal_reader` seam, and the reader is wired over the container's
  own stores, not private instances.
* **End-to-end through the shipped composition** — a Goal created through the
  container's `goal_reader` is readable by its principal and invisible to a
  foreign one, proving the seam rides the container's Workspace store.
"""

from __future__ import annotations

import logging

import pytest

from maistro.container import create_container
from maistro.goals import (
    GoalNotVisible,
    GoalRevisionDraft,
    InMemoryGoalStore,
    ScopedGoalStore,
)
from maistro.testing.postgres import postgres_dsn
from maistro.types.config import AgentConfig


async def test_container_exposes_the_goal_store_and_its_seam() -> None:
    container = await create_container(AgentConfig(router_api_key="test-key"))
    assert container.goal_store is not None, "container.goal_store is not wired"
    assert isinstance(container.goal_reader, ScopedGoalStore)
    # The seam wraps the container's own stores: authorization over this
    # deployment's Workspace store, storage over this deployment's backend.
    assert container.goal_reader.goal_store is container.goal_store
    assert container.goal_reader.workspace_store is container.workspace_store


async def test_wire_goal_store_selects_sqlite_over_a_sqlite_pool(tmp_path) -> None:
    import aiosqlite

    from maistro.goals.sqlite_store import SqliteGoalStore

    conn = await aiosqlite.connect(tmp_path / "goals.db")
    try:
        from maistro.goals.wiring import wire_goal_store

        store = await wire_goal_store(conn)
        assert isinstance(store, SqliteGoalStore)
        # ensure_schema ran: the store works immediately after wiring.
        goal = await store.create_goal(
            workspace_id="ws-1",
            project_id="prj-1",
            agent_id="agent-7",
            draft=GoalRevisionDraft(desired_state="wired", author="op"),
        )
        assert (await store.get_goal(goal.goal_id)) is not None
    finally:
        await conn.close()


async def test_wire_goal_store_falls_back_to_memory_loudly(caplog) -> None:
    from maistro.goals.wiring import wire_goal_store

    with caplog.at_level(logging.WARNING):
        store = await wire_goal_store(None)
    assert isinstance(store, InMemoryGoalStore)
    assert any("#1572" in record.message for record in caplog.records), (
        "an in-memory canonical Goal store must name the durability cost"
    )


class _UnmigratedPool:
    """A PostgreSQL pool whose schema predates migration 058.

    `fetchval` answers the wiring's `to_regclass` probe with False, which is
    all the wiring may know about it.
    """

    def __init__(self) -> None:
        self.probes: list[str] = []

    async def fetchval(self, sql: str, *args: object) -> bool:
        self.probes.append(str(args[0]))
        return False


async def test_wire_goal_store_refuses_an_unmigrated_pg_pool_as_memory(caplog) -> None:
    """A PostgreSQL pool without the Goal tables must not be answered with an
    in-process store that silently looks like one — it falls back loudly, so
    the operator runs `alembic upgrade head` instead of losing Goals."""
    from maistro.goals.wiring import GOAL_PG_TABLES, wire_goal_store

    pool = _UnmigratedPool()
    with caplog.at_level(logging.WARNING):
        store = await wire_goal_store(None, pg_pool=pool)
    assert isinstance(store, InMemoryGoalStore)
    assert pool.probes == [f"public.{table}" for table in GOAL_PG_TABLES], (
        "every migration-058 table is probed, not just the first"
    )
    assert any("alembic upgrade head" in record.message for record in caplog.records)


async def test_wire_goal_store_selects_postgres_over_a_migrated_pool() -> None:
    dsn = postgres_dsn()
    if not dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.goals.pg_store import PgGoalStore
    from maistro.goals.wiring import wire_goal_store

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        store = await wire_goal_store(None, pg_pool=pool)
        assert isinstance(store, PgGoalStore)
    finally:
        await pool.close()


async def test_goal_reader_rides_the_container_end_to_end() -> None:
    """Create through the seam, read through the seam, refuse through the
    seam — inside the shipped composition, not a hand-built fixture."""
    from maistro.workspaces.store import InMemoryWorkspaceStore

    container = await create_container(AgentConfig(router_api_key="test-key"))
    seam = container.goal_reader
    workspace = container.workspace_store
    assert isinstance(workspace, InMemoryWorkspaceStore)
    created = await workspace.create(creator_user_id="op-1", name="Goal Home")
    root_project = await workspace.project_store.root_for_workspace(created.workspace_id)
    goal = await seam.create_goal(
        principal_id="op-1",
        workspace_id=created.workspace_id,
        project_id=root_project.project_id,
        agent_id="agent-7",
        draft=GoalRevisionDraft(desired_state="shipped", author="op-1"),
    )
    assert (await seam.get_goal(goal.goal_id, principal_id="op-1")).goal_id == goal.goal_id
    with pytest.raises(GoalNotVisible):
        await seam.get_goal(goal.goal_id, principal_id="nobody-else")
