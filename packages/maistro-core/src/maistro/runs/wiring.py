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
from maistro.runs.chat_admission import ChatRunAdmitter
from maistro.runs.store import RunStore
from maistro.tasks.admission import TaskRunAdmitter

__all__ = ["wire_chat_admission", "wire_execution_spine"]


async def wire_execution_spine(
    conn: Any,
    *,
    workspace_id: str,
    intents: IntentRegistry | None = None,
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
    # The caller's registry, not a fresh default. `IntentRegistry()` builds the
    # engineering table unconditionally, so a PM-mode deployment admitted
    # `delivery`, `risk` and `reporting` to the engineering fallback agent while
    # the rest of the container routed them correctly — the canonical Graph then
    # recorded a target agent nothing else agreed with.
    admitter = TaskRunAdmitter(
        run_store,
        workspace_id=workspace_id,
        project_id=root.project_id,
        intents=intents,
    )
    return project_scope_store, run_store, admitter


def wire_chat_admission(
    run_store: RunStore,
    project_scope_store: ProjectScopeStore,
    *,
    workspace_id: str,
    intents: IntentRegistry | None = None,
) -> ChatRunAdmitter:
    """The seam a chat turn is admitted through (#131).

    Separate from :func:`wire_execution_spine` rather than another element of
    its tuple: the spine is what a process needs to execute anything, and chat
    admission is one entry point on top of it. A process that serves tasks and
    no chat has no use for this, and one that serves both should not have to
    unpack an element it ignores.

    The Root Project resolves lazily here — unlike the task admitter, which is
    built at startup with an eagerly-created root. There is no second store to
    misconfigure: this takes the spine's own, whose root
    :func:`wire_execution_spine` has already created.
    """
    return ChatRunAdmitter(
        run_store,
        workspace_id=workspace_id,
        project_store=project_scope_store,
        intents=intents,
    )
