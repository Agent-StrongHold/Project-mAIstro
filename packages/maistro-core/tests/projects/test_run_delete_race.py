"""The delete/create-run race the M1-A2 foundation review found, closed (#38).

`SqliteProjectScopeStore.delete` refuses a Project that owns Runs by asking
the Run store, and `SqliteRunStore.create_run` refuses a Graph whose Project
does not exist by asking the Project store. Two check-then-act pairs over the
same tables, from two stores sharing one connection -- and before this repair,
two private `asyncio.Lock`s. The review's deterministic interleaving paused
`delete` after its ownership SELECT answered "no Runs", let `create_run`
validate the still-present Project and commit its Run, then released `delete`
to remove the Project: a Run filed under a Project that no longer existed,
with both operations reporting success.

The repair is the one the connection already demands:

- both stores take the *per-connection* write lock (`connection_write_lock`),
  so the two check-then-act pairs are one critical section in-process --
  the same "exactly one lock per connection" rule `SqliteWorkspaceStore`
  already follows for `create_root`;
- `delete` runs every refusal, the Run-ownership one included, inside that
  section with `BEGIN IMMEDIATE`, so the reads that decide precede the DELETE
  under SQLite's write lock;
- `create_run` opens its write transaction *before* the scope validation
  read, which is #1147's rule applied to the Run side: a second process
  sharing the file serializes against the delete the same way.

The in-memory leg needs no equivalent: its ownership predicate and its `get`
never suspend (no aiosqlite worker thread to await), so single-event-loop
atomicity holds by construction -- the same doctrine the conformance suite
states for it. PostgreSQL closes the window with one `conn.transaction()`
around delete's checks and migration 010's foreign key on
`canonical_runs.project_id`.

Every test below forces the exact interleaving deterministically rather than
hoping the event loop produces it, and asserts the invariant both directions:
a Run and its Project never disagree about whether the Project exists.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope import ProjectNotEmpty
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import RunIntegrityError


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Race graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _wired_pair(
    conn: aiosqlite.Connection,
) -> tuple[SqliteProjectScopeStore, SqliteRunStore, str, str]:
    """Both stores on one connection, the way `wire_execution_spine` pairs them."""

    projects = SqliteProjectScopeStore(conn)
    await projects.ensure_schema()
    runs = SqliteRunStore(conn, project_store=projects)
    await runs.ensure_schema()
    projects.set_run_owner(runs.has_runs_in_project)
    workspace = f"ws-{id(conn):x}"
    root = await projects.create_root(workspace)
    child = await projects.create(
        workspace_id=workspace, parent_project_id=root.project_id, name="Child"
    )
    return projects, runs, workspace, child.project_id


async def _settle() -> None:
    """Give queued aiosqlite statements and ready tasks real time to run.

    Loop turns alone are not enough for a task whose statements sit behind
    aiosqlite's worker thread, so this mixes turns with small sleeps. What the
    callers assert with it is a *block*, not a completion: every block these
    tests check is structural (an `asyncio.Lock` or SQLite's file lock held by
    the paused side), so any amount of settling leaves it blocked -- while the
    un-repaired code, where nothing held the delete back, finishes well inside
    this window and the assertion fails.
    """

    for _ in range(20):
        await asyncio.sleep(0.001)


async def test_delete_holds_the_write_section_through_its_run_ownership_check(
    tmp_path: Path,
) -> None:
    """The review's interleaving: `create_run` suspended behind `delete`'s
    ownership check can no longer commit while the check's answer is stale."""

    conn = await aiosqlite.connect(tmp_path / "race-check-then-delete.db")
    try:
        projects, runs, workspace, project_id = await _wired_pair(conn)
        real_predicate = projects._owns_runs
        assert real_predicate is not None
        checked = asyncio.Event()
        release = asyncio.Event()

        async def pausing_predicate(target: str) -> bool:
            result = await real_predicate(target)
            if target == project_id:
                checked.set()
                await release.wait()
            return result

        projects._owns_runs = pausing_predicate

        delete_task = asyncio.ensure_future(projects.delete(project_id))
        await checked.wait()
        create_task = asyncio.ensure_future(runs.create_run(_graph(workspace, project_id)))
        await _settle()
        # `delete` holds the connection's write section while it waits inside
        # its ownership check, so `create_run` must not have committed a Run
        # behind that check's back. Before the repair this is exactly where
        # the orphaned Run appeared.
        assert not create_task.done()

        release.set()
        await delete_task
        with pytest.raises(RunIntegrityError, match="does not exist"):
            await create_task

        assert await projects.get(project_id) is None
        assert await runs.has_runs_in_project(project_id) is False
    finally:
        await conn.close()


async def test_create_run_holds_the_write_section_through_its_scope_validation(
    tmp_path: Path,
) -> None:
    """The mirror interleaving: a `delete` arriving between `create_run`'s
    validation and its INSERT must wait, then find the Run and refuse."""

    conn = await aiosqlite.connect(tmp_path / "race-validate-then-insert.db")
    try:
        projects, runs, workspace, project_id = await _wired_pair(conn)
        validated = asyncio.Event()
        release_create = asyncio.Event()
        paused_once = asyncio.Event()
        real_get = projects.get

        async def pausing_get(target: str):
            # One-shot: only `create_run`'s validation pauses. `delete`'s own
            # `_require` routes through `get` as well, and pausing there would
            # prove the event blocks the delete, not the write section.
            project = await real_get(target)
            if target == project_id and project is not None and not paused_once.is_set():
                paused_once.set()
                validated.set()
                await release_create.wait()
            return project

        projects.get = pausing_get  # type: ignore[method-assign]

        create_task = asyncio.ensure_future(runs.create_run(_graph(workspace, project_id)))
        await validated.wait()
        delete_task = asyncio.ensure_future(projects.delete(project_id))
        await _settle()
        # `create_run` holds the same write section from its `BEGIN IMMEDIATE`
        # through its commit, so the delete cannot slip its ownership check
        # between the validation and the INSERT. Before the repair the delete
        # completed here and the Run was then inserted under a dead Project.
        assert not delete_task.done()

        release_create.set()
        run = await create_task
        with pytest.raises(ProjectNotEmpty, match="canonical Runs"):
            await delete_task

        assert await projects.get(project_id) is not None
        assert await runs.get_run(run.run_id) is not None
    finally:
        await conn.close()


async def test_a_second_process_cannot_interleave_create_between_check_and_delete(
    tmp_path: Path,
) -> None:
    """Cross-process form: two connections to one file. The delete side holds
    SQLite's write lock from its ownership read onward; the create side's
    `BEGIN IMMEDIATE` waits behind it and then validates against committed
    state -- it cannot commit a Run for the Project the delete removed."""

    db_path = tmp_path / "race-two-processes.db"
    conn_a = await aiosqlite.connect(db_path)
    try:
        projects_a, _runs_a, workspace, project_id = await _wired_pair(conn_a)
        real_predicate = projects_a._owns_runs
        assert real_predicate is not None
        checked = asyncio.Event()
        release = asyncio.Event()

        async def pausing_predicate(target: str) -> bool:
            result = await real_predicate(target)
            if target == project_id:
                checked.set()
                await release.wait()
            return result

        projects_a._owns_runs = pausing_predicate
        delete_task = asyncio.ensure_future(projects_a.delete(project_id))
        await checked.wait()

        conn_b = await aiosqlite.connect(db_path)
        try:
            projects_b = SqliteProjectScopeStore(conn_b)
            runs_b = SqliteRunStore(conn_b, project_store=projects_b)
            create_task = asyncio.ensure_future(runs_b.create_run(_graph(workspace, project_id)))
            await _settle()
            # The delete side's write transaction is open, so the create side
            # is parked on SQLite's file lock at its own BEGIN IMMEDIATE
            # rather than validating against the pre-delete snapshot.
            assert not create_task.done()

            release.set()
            await delete_task
            with pytest.raises(RunIntegrityError, match="does not exist"):
                await asyncio.wait_for(create_task, timeout=10)

            conn_c = await aiosqlite.connect(db_path)
            try:
                cursor = await conn_c.execute(
                    "SELECT count(*) FROM canonical_runs WHERE project_id = ?",
                    (project_id,),
                )
                row = await cursor.fetchone()
                assert row is not None and row[0] == 0
                scope_c = SqliteProjectScopeStore(conn_c)
                assert await scope_c.get(project_id) is None
            finally:
                await conn_c.close()
        finally:
            await conn_b.close()
    finally:
        await conn_a.close()
