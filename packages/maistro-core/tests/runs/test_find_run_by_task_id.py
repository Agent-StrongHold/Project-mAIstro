"""#1690: `find_run_by_task_id` answers the same on every supported store.

The cross-replica receipt read resolves a task receipt id through the
canonical Run's provenance. The durable stores answer it with a provenance
expression (the PostgreSQL JSONB twin of the SQLite `json_extract`), and the
reference in-memory store scans. One assertion per store backend keeps the
three spellings from drifting: a Run admitted through the task queue's own
write path is found by its receipt id, a foreign `admission_source` filter
does not answer it, and a miss is a plain None.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import RunStatus, SqliteRunStore
from maistro.runs.admission import admit_direct_work
from maistro.runs.sources import ADMISSION_SOURCE, CHAT_SOURCE, TASK_QUEUE_SOURCE
from maistro.runs.store import InMemoryRunStore
from maistro.runs.task_kinds import DELEGATE_NODE_KIND
from maistro.tasks.admission import TASK_ID_KEY
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


async def _admit_task_run(store: Any, workspace_id: str, project_id: str, task_id: str) -> Any:
    """One Run admitted the way the task queue admits: task_id in provenance."""
    return await admit_direct_work(
        store,
        workspace_id=workspace_id,
        project_id=project_id,
        node_type=DELEGATE_NODE_KIND,
        name="queued task",
        source=TASK_QUEUE_SOURCE,
        provenance={TASK_ID_KEY: task_id},
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        initial_status=RunStatus.QUEUED,
    )


async def _admit_foreign_run(store: Any, project_id: str) -> Any:
    return await admit_direct_work(
        store,
        workspace_id="workspace-1",
        project_id=project_id,
        node_type=DELEGATE_NODE_KIND,
        name="a chat turn",
        source=CHAT_SOURCE,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )


async def _project() -> tuple[InMemoryProjectScopeStore, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    project = await projects.create(
        workspace_id="workspace-1", parent_project_id=root.project_id, name="Durable execution"
    )
    return projects, project.project_id


async def test_find_run_by_task_id_in_memory() -> None:
    projects, project_id = await _project()
    runs = InMemoryRunStore(project_store=projects)
    run = await _admit_task_run(runs, "workspace-1", project_id, "task-in-memory")
    await _admit_foreign_run(runs, project_id)

    found = await runs.find_run_by_task_id("task-in-memory")
    assert found is not None and found.run_id == run.run_id
    # The default source filter is the task queue's own; a foreign one and a
    # miss both answer None.
    assert await runs.find_run_by_task_id("task-in-memory", admission_source="chat") is None
    assert await runs.find_run_by_task_id("never-admitted") is None


async def test_find_run_by_task_id_sqlite(tmp_path: Path) -> None:
    projects, project_id = await _project()
    conn = await aiosqlite.connect(tmp_path / "task-finder.db")
    try:
        runs = SqliteRunStore(conn, project_store=projects)
        await runs.ensure_schema()
        run = await _admit_task_run(runs, "workspace-1", project_id, "task-sqlite")
        await _admit_foreign_run(runs, project_id)

        found = await runs.find_run_by_task_id("task-sqlite")
        assert found is not None and found.run_id == run.run_id
        assert await runs.find_run_by_task_id("task-sqlite", admission_source="chat") is None
        assert await runs.find_run_by_task_id("never-admitted") is None
    finally:
        await conn.close()


async def test_find_run_by_task_id_postgres(pg_pool: Any) -> None:
    # The shared `pg_pool` fixture: truncated between tests, so the
    # deterministic task id below cannot answer for a previous run's row.
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is unset; the PostgreSQL leg needs a real database")
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    # A fresh Workspace per test — the tables are shared and durable, so
    # isolating by scope is cheaper and truer than truncating between tests.
    workspace = "workspace-find-run-by-task-id"
    projects = PgProjectScopeStore(pg_pool)
    root = await projects.create_root(workspace)
    project = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Durable execution"
    )
    runs = PgRunStore(pg_pool, project_store=projects)
    # Name the receipt id so the assertion reads as data, not as a
    # machine-generated id nobody could correlate.
    task_id = "task-pg-1690-finder"
    run = await _admit_task_run(runs, workspace, project.project_id, task_id)
    found = await runs.find_run_by_task_id(task_id)
    assert found is not None and found.run_id == run.run_id
    assert await runs.find_run_by_task_id(task_id, admission_source="chat") is None
    assert await runs.find_run_by_task_id("never-admitted") is None


def test_chat_source_constant_is_what_the_filter_rejects() -> None:
    # Guard the test's own assumption: the foreign source spelled in the
    # store tests is the chat admission source, not an invented string.
    assert ADMISSION_SOURCE == "admission_source"
    assert CHAT_SOURCE == "chat"
