"""The container and the server admit into the same, real spine (#41).

Wiring is where an execution-identity claim quietly becomes false: a store that
is durable in one process and ephemeral in another, or a Root Project resolved
lazily so the first submission is the one that discovers it does not exist.
These hold the wiring to producing objects that agree with each other.
"""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.store import InMemoryRunStore
from maistro.runs.wiring import wire_execution_spine
from maistro.tasks.models import TaskCreate
from maistro.tasks.queue import TaskQueue


async def test_without_a_connection_the_spine_is_in_memory() -> None:
    spine = await wire_execution_spine(None, workspace_id="w1")
    scope_store, run_store, admitter = spine.project_store, spine.run_store, spine.task_admitter

    assert isinstance(scope_store, InMemoryProjectScopeStore)
    assert isinstance(run_store, InMemoryRunStore)
    assert admitter is not None


async def test_with_a_connection_the_spine_is_durable() -> None:
    async with aiosqlite.connect(":memory:") as conn:
        spine = await wire_execution_spine(conn, workspace_id="w1")
        scope_store, run_store = spine.project_store, spine.run_store

        assert type(scope_store).__name__ == "SqliteProjectScopeStore"
        assert type(run_store).__name__ == "SqliteRunStore"


async def test_the_root_project_exists_before_the_first_submission() -> None:
    """Resolved eagerly: a Run store refuses a Graph in a Project that isn't
    there, so a lazy root turns misconfiguration into a first-task failure."""
    scope_store = (await wire_execution_spine(None, workspace_id="w1")).project_store

    root = await scope_store.root_for_workspace("w1")

    assert root.is_root


@pytest.mark.parametrize("durable", [False, True])
async def test_a_queue_on_the_wired_spine_admits_a_resolvable_run(durable: bool) -> None:
    """The claim that matters: the run_id a submission returns resolves in the
    same store the wiring handed back, in both backends."""
    conn = await aiosqlite.connect(":memory:") if durable else None
    try:
        spine = await wire_execution_spine(conn, workspace_id="w1")
        run_store = spine.run_store
        queue = TaskQueue(admitter=spine.task_admitter)

        task = await queue.submit(TaskCreate(description="ship it", task_type="code"))

        assert task.run_id
        run = await run_store.get_run(task.run_id)
        assert run is not None
        assert run.workspace_id == "w1"
    finally:
        if conn is not None:
            await conn.close()


async def test_the_workspace_is_the_one_asked_for() -> None:
    spine = await wire_execution_spine(None, workspace_id="tenant-a")
    run_store = spine.run_store
    queue = TaskQueue(admitter=spine.task_admitter)

    task = await queue.submit(TaskCreate(description="ship it"))

    run = await run_store.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "tenant-a"


# ── PostgreSQL is selected when the deployment has one (#132) ─────


async def test_with_a_pg_pool_the_spine_is_postgres(pg_pool) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    spine = await wire_execution_spine(None, workspace_id="wiring-pg", pg_pool=pg_pool)
    scope_store, run_store, admitter = spine.project_store, spine.run_store, spine.task_admitter

    assert type(scope_store).__name__ == "PgProjectScopeStore"
    assert type(run_store).__name__ == "PgRunStore"
    assert admitter is not None


async def test_a_pg_pool_wins_over_a_sqlite_connection(pg_pool) -> None:
    """Both configured is a misconfiguration, but it must resolve the way
    ADR-082226-5104 orders them rather than by argument order."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    conn = await aiosqlite.connect(":memory:")
    try:
        run_store = (
            await wire_execution_spine(conn, workspace_id="wiring-both", pg_pool=pg_pool)
        ).run_store

        assert type(run_store).__name__ == "PgRunStore"
    finally:
        await conn.close()


async def test_a_run_admitted_on_postgres_outlives_its_store(pg_pool) -> None:
    """The claim #132 exists to make true: a fresh store object — standing in
    for a restarted process — resolves a Run the previous one admitted."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    spine = await wire_execution_spine(None, workspace_id="wiring-restart", pg_pool=pg_pool)
    queue = TaskQueue(admitter=spine.task_admitter)
    task = await queue.submit(TaskCreate(description="survive", task_type="code"))

    again = await wire_execution_spine(None, workspace_id="wiring-restart", pg_pool=pg_pool)
    run = await again.run_store.get_run(task.run_id or "")

    assert run is not None
    assert run.workspace_id == "wiring-restart"
    assert run.graph.materialize().nodes[0].parameters["to_agent"] == "artificer"
