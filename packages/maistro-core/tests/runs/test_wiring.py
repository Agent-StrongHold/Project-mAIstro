"""The container and the server admit into the same, real spine (#41).

Wiring is where an execution-identity claim quietly becomes false: a store that
is durable in one process and ephemeral in another, or a Root Project resolved
lazily so the first submission is the one that discovers it does not exist.
These hold the wiring to producing three objects that agree with each other.
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
    scope_store, run_store, admitter = await wire_execution_spine(None, workspace_id="w1")

    assert isinstance(scope_store, InMemoryProjectScopeStore)
    assert isinstance(run_store, InMemoryRunStore)
    assert admitter is not None


async def test_with_a_connection_the_spine_is_durable() -> None:
    async with aiosqlite.connect(":memory:") as conn:
        scope_store, run_store, _admitter = await wire_execution_spine(conn, workspace_id="w1")

        assert type(scope_store).__name__ == "SqliteProjectScopeStore"
        assert type(run_store).__name__ == "SqliteRunStore"


async def test_the_root_project_exists_before_the_first_submission() -> None:
    """Resolved eagerly: a Run store refuses a Graph in a Project that isn't
    there, so a lazy root turns misconfiguration into a first-task failure."""
    scope_store, _run_store, _admitter = await wire_execution_spine(None, workspace_id="w1")

    root = await scope_store.root_for_workspace("w1")

    assert root.is_root


@pytest.mark.parametrize("durable", [False, True])
async def test_a_queue_on_the_wired_spine_admits_a_resolvable_run(durable: bool) -> None:
    """The claim that matters: the run_id a submission returns resolves in the
    same store the wiring handed back, in both backends."""
    conn = await aiosqlite.connect(":memory:") if durable else None
    try:
        _scope_store, run_store, admitter = await wire_execution_spine(conn, workspace_id="w1")
        queue = TaskQueue(admitter=admitter)

        task = await queue.submit(TaskCreate(description="ship it", task_type="code"))

        assert task.run_id
        run = await run_store.get_run(task.run_id)
        assert run is not None
        assert run.workspace_id == "w1"
    finally:
        if conn is not None:
            await conn.close()


async def test_the_workspace_is_the_one_asked_for() -> None:
    _scope_store, run_store, admitter = await wire_execution_spine(None, workspace_id="tenant-a")
    queue = TaskQueue(admitter=admitter)

    task = await queue.submit(TaskCreate(description="ship it"))

    run = await run_store.get_run(task.run_id or "")
    assert run is not None
    assert run.workspace_id == "tenant-a"
