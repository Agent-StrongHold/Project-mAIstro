"""Wiring the canonical Run spine and the seam work is admitted through (#41).

Lives here rather than in `maistro.container` because more than one process
needs it: the DI container wires it for the Conductor, and maistro-server's
`/tasks` API needs the same three objects without building a whole Container.
Duplicating the wiring in each would be how the two drift into disagreeing about
which Workspace a Run belongs to.
"""

from __future__ import annotations

from typing import Any

from maistro.agents.intents import IntentRegistry
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.store import RunStore
from maistro.tasks.admission import WorkspaceRoutingAdmitter

__all__ = ["wire_execution_spine"]


async def wire_execution_spine(
    conn: Any,
    *,
    workspace_id: str,
    intents: IntentRegistry | None = None,
) -> tuple[ProjectScopeStore, RunStore, WorkspaceRoutingAdmitter]:
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

    # The caller's registry, not a fresh default. `IntentRegistry()` builds the
    # engineering table unconditionally, so a PM-mode deployment admitted
    # `delivery`, `risk` and `reporting` to the engineering fallback agent while
    # the rest of the container routed them correctly — the canonical Graph then
    # recorded a target agent nothing else agreed with.
    admitter = WorkspaceRoutingAdmitter(
        run_store,
        project_scope_store,
        default_workspace_id=workspace_id,
        intents=intents,
    )
    # Priming the default Workspace is what keeps the eager-Root guarantee in
    # the docstring above true for the case every deployment has. Workspaces a
    # submission names later (#158) are built on first use, because they do not
    # exist yet at startup.
    await admitter.admitter_for(workspace_id)
    return project_scope_store, run_store, admitter
