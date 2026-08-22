"""Wiring the canonical Run spine and the seam work is admitted through (#41).

Lives here rather than in `maistro.container` because more than one process
needs it: the DI container wires it for the Conductor, and maistro-server's
`/tasks` API needs the same three objects without building a whole Container.
Duplicating the wiring in each would be how the two drift into disagreeing about
which Workspace a Run belongs to.
"""

from __future__ import annotations

from typing import Any

from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.store import RunStore
from maistro.tasks.admission import TaskRunAdmitter

__all__ = ["wire_execution_spine"]


async def wire_execution_spine(
    conn: Any,
    *,
    workspace_id: str,
) -> tuple[ProjectScopeStore, RunStore, TaskRunAdmitter]:
    """Wire the canonical Run spine and the seam tasks are admitted through (#41).

    Durable when a SQLite connection is open, in-memory otherwise — the same
    split every other store in this container follows. The Workspace's Root
    Project is created eagerly rather than on first submission: a Run store
    refuses to file a Graph in a Project that does not exist, so resolving it
    lazily would turn a startup misconfiguration into a runtime failure on
    somebody's first task.
    """
    project_scope_store: ProjectScopeStore
    run_store: RunStore
    if conn is not None:
        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.runs.sqlite_store import SqliteRunStore

        sqlite_scope_store = SqliteProjectScopeStore(conn)
        await sqlite_scope_store.ensure_schema()
        sqlite_run_store = SqliteRunStore(conn, project_store=sqlite_scope_store)
        await sqlite_run_store.ensure_schema()
        project_scope_store = sqlite_scope_store
        run_store = sqlite_run_store
    else:
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore

        project_scope_store = InMemoryProjectScopeStore()
        run_store = InMemoryRunStore(project_store=project_scope_store)

    root = await project_scope_store.create_root(workspace_id)
    admitter = TaskRunAdmitter(
        run_store,
        workspace_id=workspace_id,
        project_id=root.project_id,
    )
    return project_scope_store, run_store, admitter
