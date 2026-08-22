"""Wiring the canonical Run spine and the seam work is admitted through (#41).

Lives here rather than in `maistro.container` because more than one process
needs it: the DI container wires it for the Conductor, and maistro-server's
`/tasks` API needs the same objects without building a whole Container.
Duplicating the wiring in each would be how the two drift into disagreeing about
which Workspace a Run belongs to.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from maistro.agents.intents import IntentRegistry
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.chat import ChatRunAdmitter
from maistro.runs.retention import RetentionPolicy
from maistro.runs.store import RunStore
from maistro.tasks.admission import TaskRunAdmitter

__all__ = ["ExecutionSpine", "wire_execution_spine"]


class ExecutionSpine(NamedTuple):
    """Everything an entry point needs to admit work as a canonical Run."""

    project_store: ProjectScopeStore
    run_store: RunStore
    task_admitter: TaskRunAdmitter
    chat_admitter: ChatRunAdmitter


async def wire_execution_spine(
    conn: Any,
    *,
    workspace_id: str,
    intents: IntentRegistry | None = None,
    pg_pool: Any = None,
    chat_retention: RetentionPolicy | None = None,
) -> ExecutionSpine:
    """Wire the canonical Run spine and the seam tasks are admitted through (#41).

    PostgreSQL when the deployment has one, SQLite for a homelab, in-memory
    otherwise — the same backend order every other store follows, and the order
    ADR-082226-5104 requires: the spine is the one thing that must not be
    ephemeral, because it is what an audit, a recovery, a retry and a resumed
    HITL pause all read.

    The Workspace's Root Project is created eagerly rather than on first
    submission: a Run store refuses to file a Graph in a Project that does not
    exist, so resolving it lazily would turn a startup misconfiguration into a
    runtime failure on somebody's first task.
    """
    project_scope_store: ProjectScopeStore
    run_store: RunStore
    if pg_pool is not None:
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        # No ensure_schema: these tables come from `alembic/versions/010`, and
        # the container's PostgreSQL preflight already refuses an unmigrated
        # database by name. A store that quietly created its own tables would be
        # a second schema owner and a second thing to keep in step.
        project_scope_store = PgProjectScopeStore(pg_pool)
        run_store = PgRunStore(pg_pool, project_store=project_scope_store)
    elif conn is not None:
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
    # Same store, same Workspace, same intent table — a chat turn and a task
    # differ in retention and in nothing else (#131, ADR-082226-c126).
    chat_admitter = ChatRunAdmitter(
        run_store,
        workspace_id=workspace_id,
        project_id=root.project_id,
        intents=intents,
        retention=chat_retention,
    )
    return ExecutionSpine(project_scope_store, run_store, admitter, chat_admitter)
