"""The Goal store is wired, selected by backend, and exposed by the shipped
Container (#1572).

"Composed in production rather than only in tests" is the acceptance criterion
the store cannot prove about itself: a `goal_store` field nothing constructs is
a library, not composition. So this file proves three claims:

* **Backend selection** — `wire_goal_store` picks the durable twin over the
  SQLite pool the deployment already has, and the PostgreSQL store over a pool
  whose database has not run `alembic upgrade head` yet: the missing
  migration-063 tables are created at wiring (`ensure_goal_schema`, the event
  stores' "wiring creates the schema it needs" contract) so the Container comes
  up with Goals on the durable backend it selected — never answered with an
  in-process store that merely looks the same, the split-backend defect the
  Workspace wiring documents. No database at all means the in-memory reference
  — loudly, since canonical Goals that die with the process are not canonical.
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
import uuid

import pytest

from maistro.container import create_container
from maistro.goals import (
    GoalNotVisible,
    GoalRevisionDraft,
    InMemoryGoalStore,
    ScopedGoalStore,
)
from maistro.goals.wiring import GOAL_PG_TABLES
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


class _RecordingPool:
    """Answer only the PostgreSQL bootstrap path; never substitute storage.

    `ensure_goal_schema` acquires a connection, opens a transaction, takes the
    advisory lock and executes the DDL — this double records exactly those
    statements and nothing else, so the test can pin what wiring ran without a
    live server.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, sql: str, *args: object) -> None:
        self.statements.append(sql)

    def acquire(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _conn():
            yield self

        return _conn()

    def transaction(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _tx():
            yield

        return _tx()


@pytest.fixture(params=[False, True], ids=["no-sqlite", "sqlite-available"])
async def optional_sqlite(request, tmp_path):
    if not request.param:
        yield None
        return
    import aiosqlite

    async with aiosqlite.connect(tmp_path / "fallback.db") as conn:
        yield conn


async def test_wire_goal_store_creates_the_schema_an_unmigrated_pg_pool_needs(
    optional_sqlite,
) -> None:
    """A pool that never ran `alembic upgrade head` gets its Goal tables here.

    The Container must come up on a database without the migration-063 tables —
    the durable-events contract the refusal broke — and Goals must stay on the
    durable PostgreSQL the deployment selected, never fall back to SQLite or
    memory. So wiring creates the schema (advisory-locked, like every
    concurrent bootstrap path) and selects the durable store.
    """
    from maistro.goals.pg_store import PgGoalStore
    from maistro.goals.wiring import wire_goal_store

    pool = _RecordingPool()
    store = await wire_goal_store(optional_sqlite, pg_pool=pool)

    assert isinstance(store, PgGoalStore)
    assert any("pg_advisory_xact_lock" in sql for sql in pool.statements), (
        "concurrent bootstrap must serialise on the advisory lock"
    )
    ddl = "\n".join(pool.statements)
    for table in GOAL_PG_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl
    if optional_sqlite is not None:
        async with optional_sqlite.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ) as cursor:
            assert await cursor.fetchall() == [], (
                "a PostgreSQL pool must not initialize a SQLite fallback store"
            )


async def test_wire_goal_store_keeps_a_migrated_pg_pool_even_with_sqlite(
    optional_sqlite,
) -> None:
    """Exercise backend selection without claiming this stub is a live PG test."""
    from maistro.goals.pg_store import PgGoalStore
    from maistro.goals.wiring import wire_goal_store

    pool = _RecordingPool()
    store = await wire_goal_store(optional_sqlite, pg_pool=pool)
    assert isinstance(store, PgGoalStore)
    assert any("canonical_goals" in sql for sql in pool.statements)


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


async def test_wiring_brings_a_bare_database_up_with_the_goal_schema() -> None:
    """Against a real server: a database that never ran the chain comes up.

    The durable-events job caught exactly this: `create_container` wired a bare
    PostgreSQL service and the Goal refusal killed the Container before the
    event schema existed. Here the same shape, on a throwaway database of its
    own so no migrated database is touched: wire, then create and read a Goal
    through the store that wiring answered with — durable tables, not a
    refusal, not a second backend.
    """
    dsn = postgres_dsn()
    if not dsn:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a reachable PostgreSQL server")
    asyncpg = pytest.importorskip("asyncpg")
    psycopg = pytest.importorskip("psycopg")

    from maistro.goals import GoalRevisionDraft
    from maistro.goals.pg_store import PgGoalStore
    from maistro.goals.wiring import GOAL_PG_TABLES, wire_goal_store

    base = dsn.rsplit("/", 1)[0]
    name = f"goal_wiring_{uuid.uuid4().hex[:12]}"
    bare = f"{base}/{name}"
    # Admin over the existing test database (a URL without one would connect
    # to a database named after the user): CREATE DATABASE needs autocommit.
    with psycopg.connect(dsn, autocommit=True) as admin:  # type: ignore[arg-type]
        admin.execute(f'CREATE DATABASE "{name}"')  # type: ignore[union-attr]
    try:
        pool = await asyncpg.create_pool(bare, min_size=1, max_size=2)
        try:
            rows = await pool.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
            assert {row["tablename"] for row in rows} == set(), (
                "a bare database must not ship user tables"
            )

            store = await wire_goal_store(None, pg_pool=pool)
            assert isinstance(store, PgGoalStore)
            rows = await pool.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
            assert {row["tablename"] for row in rows} == set(GOAL_PG_TABLES)

            goal = await store.create_goal(
                workspace_id="ws-bare",
                project_id="prj-bare",
                agent_id="agent-1",
                draft=GoalRevisionDraft(desired_state="up", author="op"),
            )
            read = await store.get_goal(goal.goal_id)
            assert read is not None and read.current_revision == 1
        finally:
            await pool.close()
    finally:
        with psycopg.connect(dsn, autocommit=True) as cleanup:  # type: ignore[arg-type]
            cleanup.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # type: ignore[union-attr]


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
