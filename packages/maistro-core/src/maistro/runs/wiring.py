"""Wiring the canonical Run spine and the seam work is admitted through (#41).

Lives here rather than in `maistro.container` because more than one process
needs it: the DI container wires it for the Conductor, and maistro-server's
`/tasks` API needs the same three objects without building a whole Container.
Duplicating the wiring in each would be how the two drift into disagreeing about
which Workspace a Run belongs to.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from maistro.agents.intents import IntentRegistry
from maistro.archive.protocols import ArchiveStore
from maistro.graph.templates import GraphTemplateStore, NodeTemplateStore
from maistro.projects.scope_store import ProjectScopeStore
from maistro.runs.chat_admission import ChatRunAdmitter
from maistro.runs.store import RunStore
from maistro.scheduling.store import ScheduleStore
from maistro.tasks.admission import WorkspaceRoutingAdmitter

__all__ = ["wire_chat_admission", "wire_execution_spine"]


logger = logging.getLogger(__name__)

#: Tables the PostgreSQL spine needs before it may be selected. Defined here
#: rather than in `container` because the import runs that way: `container`
#: imports this module, so this module cannot import it back.
SPINE_PG_TABLES: Final = (
    "canonical_projects",
    "canonical_runs",
    "canonical_node_runs",
    "canonical_attempts",
    "graph_templates",
)


async def _spine_is_migrated(pg_pool: Any) -> bool:
    """Whether this pool's database actually has the spine's tables.

    A pool reached here two ways, and only one of them has been checked. The
    URL path runs `_require_postgres_schema` at startup and refuses an
    unmigrated database by name, so by the time it gets here the answer is
    always yes. The caller-supplied pool (#135's seam — a test with a fixture,
    an embedding application that opened its own) has been through no preflight
    at all, and may legitimately hold only the tables that caller cared about.

    Assuming yes there turns "this pool has no spine tables" into
    `UndefinedTableError` from inside `create_container`, which is a startup
    crash for a deployment that never asked for a durable spine. Probing is one
    round trip, once, and lets the caller keep the backend it did ask for.

    Falling back is warned about rather than silent: a durable pool that ends up
    with an in-memory spine is exactly the shape of #122, and the difference
    between that defect and this fallback is entirely that this one says so.
    """
    missing = [
        table
        for table in SPINE_PG_TABLES
        if not await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
    ]
    if not missing:
        return True
    logger.warning(
        "PostgreSQL pool is missing the canonical spine's tables (%s), so Runs are "
        "in-process and lost on restart. Run `alembic upgrade head` against this "
        "database to make the spine durable (#132).",
        ", ".join(missing),
    )
    return False


async def _pg_node_template_store(pg_pool: Any) -> NodeTemplateStore:
    """The PostgreSQL NodeTemplate registry, or an in-memory one with a warning.

    Probed separately from `SPINE_PG_TABLES`, for the reason `_pg_schedule_store`
    records: a Run does not need a NodeTemplate to exist, so a database migrated
    to `018` but not `019` has a perfectly good durable spine. Folding
    `node_templates` into that tuple would drop such a deployment's Runs to
    in-memory over a table it never asked for.

    Warned rather than silent: a durable pool that ends up with ephemeral
    NodeTemplates is the shape of #122, and every Node instantiated from one
    would record provenance naming a template that vanishes on restart.
    """
    if await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", "public.node_templates"):
        from maistro.graph.pg_templates import PgNodeTemplateStore

        return PgNodeTemplateStore(pg_pool)

    from maistro.graph.templates import InMemoryNodeTemplateStore

    logger.warning(
        "PostgreSQL pool has no `node_templates` table, so NodeTemplates are in-process "
        "and lost on restart, and every Node instantiated from one records provenance "
        "nothing can resolve afterwards. Run `alembic upgrade head` against this "
        "database to make them durable (#556)."
    )
    return InMemoryNodeTemplateStore()


async def _pg_schedule_store(pg_pool: Any) -> ScheduleStore:
    """The PostgreSQL schedule store, or an in-memory one with a warning.

    Probed separately from `SPINE_PG_TABLES` rather than added to it. A Run does
    not need a schedule to exist, so a database migrated to `015` but not `016`
    has a perfectly good durable spine — folding `schedules` into that tuple
    would drop such a deployment's Runs to in-memory over a table it never asked
    for, which is a far worse failure than the one being guarded against.

    Falling back is warned about rather than silent, for the same reason
    `_spine_is_migrated` warns: a durable pool that ends up with ephemeral
    schedules is the shape of #122, and saying so is the whole difference.
    """
    if await pg_pool.fetchval("SELECT to_regclass($1) IS NOT NULL", "public.schedules"):
        from maistro.scheduling.pg_store import PgScheduleStore

        return PgScheduleStore(pg_pool)

    from maistro.scheduling.store import InMemoryScheduleStore

    logger.warning(
        "PostgreSQL pool has no `schedules` table, so schedules are in-process and "
        "lost on restart, and two scheduler replicas cannot share a cursor. Run "
        "`alembic upgrade head` against this database to make them durable (#231)."
    )
    return InMemoryScheduleStore()


async def wire_execution_spine(
    conn: Any,
    *,
    workspace_id: str,
    intents: IntentRegistry | None = None,
    pg_pool: Any = None,
    archive_store: ArchiveStore | None = None,
) -> tuple[
    ProjectScopeStore,
    RunStore,
    WorkspaceRoutingAdmitter,
    GraphTemplateStore,
    ScheduleStore,
    NodeTemplateStore,
]:
    """Wire the canonical Run spine and the seam tasks are admitted through (#41).

    PostgreSQL when the deployment has one, SQLite for a homelab, in-memory
    otherwise — the same backend order every other store follows, and the order
    ADR-082226-5104 requires: the spine is the one thing that must not be
    ephemeral, because it is what an audit, a recovery, a retry and a resumed
    HITL pause all read (#132).

    The Workspace's Root Project is created eagerly rather than on first
    submission: a Run store refuses to file a Graph in a Project that does not
    exist, so resolving it lazily would turn a startup misconfiguration into a
    runtime failure on somebody's first task.

    The Graph template store is wired here rather than separately because a
    Run's Graph and the template it was instantiated from must live in the same
    database — a registry pointing at one and a spine at another is how a Run
    ends up citing a template version nothing can resolve.

    `archive_store` reaches the two stores that can use it (#273). It is the
    Container's own `archive_store`, so a deployment gets one archive tier
    rather than one per subsystem, and passing None — the default, and what
    every deployment has today — leaves the tier off exactly as f436 decision 9
    requires. `SqliteRunStore` does not take it: the homelab twin has no
    archive columns, and `ColdRunArchiver` is a capability protocol precisely so
    a store may decline the tier instead of stubbing it.
    """
    project_scope_store: ProjectScopeStore
    run_store: RunStore
    template_store: GraphTemplateStore
    schedule_store: ScheduleStore
    node_template_store: NodeTemplateStore
    if pg_pool is not None and await _spine_is_migrated(pg_pool):
        # No ensure_schema: these tables come from `alembic/versions/012` and
        # `014`. A store that quietly created its own tables would be a second
        # schema owner and a second thing to keep in step — which is why the
        # check above *probes* rather than creates.
        from maistro.graph.pg_templates import PgGraphTemplateStore
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        project_scope_store = PgProjectScopeStore(pg_pool)
        run_store = PgRunStore(
            pg_pool, project_store=project_scope_store, archive_store=archive_store
        )
        template_store = PgGraphTemplateStore(pg_pool)
        schedule_store = await _pg_schedule_store(pg_pool)
        node_template_store = await _pg_node_template_store(pg_pool)
    elif conn is not None:
        from maistro.graph.sqlite_templates import (
            SqliteGraphTemplateStore,
            SqliteNodeTemplateStore,
        )
        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.runs.sqlite_store import SqliteRunStore
        from maistro.scheduling.store import SqliteScheduleStore

        sqlite_scope_store = SqliteProjectScopeStore(conn)
        await sqlite_scope_store.ensure_schema()
        sqlite_run_store = SqliteRunStore(conn, project_store=sqlite_scope_store)
        await sqlite_run_store.ensure_schema()
        sqlite_template_store = SqliteGraphTemplateStore(conn)
        await sqlite_template_store.ensure_schema()
        sqlite_schedule_store = SqliteScheduleStore(conn)
        await sqlite_schedule_store.ensure_schema()
        sqlite_node_template_store = SqliteNodeTemplateStore(conn)
        await sqlite_node_template_store.ensure_schema()
        node_template_store = sqlite_node_template_store
        project_scope_store = sqlite_scope_store
        run_store = sqlite_run_store
        template_store = sqlite_template_store
        schedule_store = sqlite_schedule_store
    else:
        from maistro.graph.templates import (
            InMemoryGraphTemplateStore,
            InMemoryNodeTemplateStore,
        )
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.runs.store import InMemoryRunStore
        from maistro.scheduling.store import InMemoryScheduleStore

        project_scope_store = InMemoryProjectScopeStore()
        run_store = InMemoryRunStore(project_store=project_scope_store, archive_store=archive_store)
        template_store = InMemoryGraphTemplateStore()
        schedule_store = InMemoryScheduleStore()
        node_template_store = InMemoryNodeTemplateStore()

    # The Project store refuses to delete a Project that owns Runs, and only
    # the Run store can answer that. PostgreSQL has a foreign key for it; this
    # is how the in-memory and SQLite stores learn the same rule.
    register = getattr(project_scope_store, "set_run_owner", None)
    if register is not None:
        register(run_store.has_runs_in_project)

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
    return (
        project_scope_store,
        run_store,
        admitter,
        template_store,
        schedule_store,
        node_template_store,
    )


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
