"""Retention deletes by named scope, and accounts for every dependent (#1175).

The store's purge predicates are proved across all three backends in
`test_retention_conformance`; the sweeper's scope plumbing in
`test_retention_policy`. What this suite holds is the intersection the issue
names: a purge invoked with one Workspace's authority must be unable to touch
another Workspace's evidence, and a completed purge must leave no canonical
dependent dangling — continuations go with their Run, events survive by
policy and are counted, schedule claims die with their Run rows.

Two Workspaces everywhere. The references cross the scope boundary on
purpose: Workspace A's sweep runs while Workspace B holds expired Runs,
continuations, events and a schedule claim that would all be destroyed by the
pre-#1175 unscoped purge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import aiosqlite
import pytest

from maistro.events.envelope import EventEnvelope, InMemoryEventStore
from maistro.graph import Graph, Node
from maistro.graph.durable_runs.continuation import (
    GraphContinuation,
    GraphContinuationStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
)
from maistro.graph.execution_state import GraphExecutionState
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.retention_scope import (
    GlobalRetentionScope,
    WorkspaceRetentionScope,
)
from maistro.runs.store import DuplicateOccurrence, InMemoryRunStore

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
EXPIRED = NOW - timedelta(seconds=1)

WORKSPACE_A = "workspace-a"
WORKSPACE_B = "workspace-b"


def _scope_a(world: Any) -> WorkspaceRetentionScope:
    """Workspace A's scope, read from the world rather than a constant.

    The PostgreSQL leg isolates tests by Workspace — the id embeds the test
    name — so a module-level scope would name a Workspace no row belongs to
    and every purge on that leg would be a silent no-op.
    """
    return WorkspaceRetentionScope(workspace_id=world.a[0])


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Scope retention graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _expired_terminal_run(world: Any, workspace: str, project_id: str) -> Any:
    """A completed Run past its deadline, with one NodeRun and one Attempt."""
    store = world.runs
    run = await store.create_run(_graph(workspace, project_id), retention_expires_at=EXPIRED)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED)
    await store.transition_run(run.run_id, RunStatus.COMPLETED)
    return run


async def _continuation_for(store: GraphContinuationStore, run: Any) -> GraphContinuation:
    return await store.create(
        GraphContinuation(
            run_id=run.run_id,
            graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
            status=run.status,
            project_id=run.project_id,
        )
    )


async def _event_for(store: Any, workspace: str, run: Any) -> EventEnvelope:
    return await store.append(
        EventEnvelope(
            type="run.completed",
            workspace_id=workspace,
            project_id=run.project_id,
            run_id=run.run_id,
            payload={"run_id": run.run_id},
        )
    )


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def scope_world(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """Two Workspaces, their dependent stores, and the purge seam between them.

    The SQLite leg wires the continuation and Event stores onto the spine's
    own connection — the homelab layout. The PostgreSQL leg uses the migrated
    database, where both dependent tables already exist. The memory leg has
    neither table by construction: its Event store is an in-process object the
    purge cannot see, and that boundary is itself part of what the tests pin.
    """
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.events.pg_envelope import PgEventStore
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        projects = PgProjectScopeStore(pg_pool)
        scoped: dict[str, tuple[str, str]] = {}
        for name in ("a", "b"):
            workspace = f"scope-{name}-{request.node.name}"
            root = await projects.create_root(workspace)
            project = await projects.create(
                workspace_id=workspace,
                parent_project_id=root.project_id,
                name="Scoped",
            )
            scoped[name] = (workspace, project.project_id)
        events = PgEventStore(pg_pool)
        await events.ensure_schema()
        # Bare `return` after the yield, never `return <value>`: a fixture
        # that yields anywhere is an async generator, and a valued return
        # from one is a SyntaxError. Each branch yields exactly once and
        # returns, so no leg falls through into another's setup.
        yield SimpleNamespace(
            backend="postgres",
            runs=PgRunStore(pg_pool, project_store=projects),
            continuations=None,  # the migrated database owns the table
            events=events,
            a=scoped["a"],
            b=scoped["b"],
        )
        return
        return  # async-generator teardown must not fall into the sqlite leg

    projects = InMemoryProjectScopeStore()
    scoped: dict[str, tuple[str, str]] = {}
    for name in ("a", "b"):
        root = await projects.create_root(f"workspace-{name}")
        project = await projects.create(
            workspace_id=f"workspace-{name}",
            parent_project_id=root.project_id,
            name="Scoped",
        )
        scoped[name] = (f"workspace-{name}", project.project_id)

    if request.param == "memory":
        yield SimpleNamespace(
            backend="memory",
            runs=InMemoryRunStore(
                project_store=projects,
                continuation_store=InMemoryGraphContinuationStore(),
            ),
            continuations=None,  # reachable through the run store's seam only
            events=InMemoryEventStore(),
            a=scoped["a"],
            b=scoped["b"],
        )
        return
        return  # async-generator teardown must not fall into the sqlite leg

    conn = await aiosqlite.connect(":memory:")
    from maistro.runs.sqlite_store import SqliteRunStore

    run_store = SqliteRunStore(conn, project_store=projects)
    await run_store.ensure_schema()
    continuations = SqliteGraphContinuationStore(conn)
    await continuations.ensure_schema()
    from maistro.events.envelope import SqliteEventStore

    events = SqliteEventStore(conn)
    await events.ensure_schema()
    # The connection must be closed on teardown: aiosqlite runs its driver on
    # a non-daemon thread, and an open connection would keep the test process
    # alive after the suite finished.
    try:
        yield SimpleNamespace(
            backend="sqlite",
            runs=run_store,
            continuations=continuations,
            events=events,
            a=scoped["a"],
            b=scoped["b"],
        )
    finally:
        await conn.close()


def _continuation_store_or_skip(world: Any) -> Any:
    """The continuation store a test can read, on the backends that expose one.

    The memory leg wires its continuation store into the run store's purge
    seam but keeps no separately-readable handle, so the continuation tests
    are sqlite/postgres legs; the memory scoping tests above need no handle.
    """
    store = world.continuations
    if store is None:
        pytest.skip("backend exposes no separately-readable continuation store")
    assert store is not None  # narrowed above; names the invariant for checkers
    return store


# ── the boundary itself ───────────────────────────────────────────


async def test_one_workspaces_sweep_cannot_touch_another(scope_world: Any) -> None:
    """Workspace A's purge deletes A's expired Run and its spine, and is
    unable to see B's — however expired B's Runs are."""
    world = scope_world
    run_a = await _expired_terminal_run(world, *world.a)
    # B is expired but still running — the deadline is a floor — so it is not
    # even a purge candidate; A is the only thing A's sweep may select.
    run_b = await world.runs.create_run(_graph(*world.b), retention_expires_at=EXPIRED)
    await world.runs.transition_run(run_b.run_id, RunStatus.QUEUED)
    await world.runs.transition_run(run_b.run_id, RunStatus.RUNNING)
    node_run_b = await world.runs.create_node_run(run_b.run_id, node_id="node-1")

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    assert outcome.runs == 1
    assert outcome.workspace_id == world.a[0]
    assert not outcome.is_global
    assert await world.runs.get_run(run_a.run_id) is None
    assert await world.runs.get_run(run_b.run_id) is not None
    assert await world.runs.get_node_run(node_run_b.node_run_id) is not None


async def test_the_purge_inventories_its_spine_dependents(scope_world: Any) -> None:
    """The outcome counts the NodeRuns and Attempts that went with the Run —
    a health metric of "1" would describe a sweep that deleted four rows."""
    world = scope_world
    await _expired_terminal_run(world, *world.a)
    await _expired_terminal_run(world, *world.b)

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    # A's Run, its one NodeRun and one Attempt: the outcome counts every row
    # the sweep actually deleted, not just the Runs at the top of the spine.
    assert outcome.runs == 1
    assert outcome.node_runs == 1
    assert outcome.attempts == 1


# ── continuations: execution state dies with its Run ──────────────


async def test_a_continuation_does_not_outlive_its_run(scope_world: Any) -> None:
    world = scope_world
    run_a = await _expired_terminal_run(world, *world.a)
    run_b = await _expired_terminal_run(world, *world.b)
    store_a = _continuation_store_or_skip(world)
    await _continuation_for(store_a, run_a)
    await _continuation_for(store_a, run_b)

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    assert outcome.continuations == 1
    assert await store_a.get(run_a.run_id) is None
    # B's traversal state is untouched: it belongs to a live Run.
    assert await store_a.get(run_b.run_id) is not None


# ── events: attribution history outlives the Run, and says so ─────


async def test_events_survive_a_purge_and_are_counted(scope_world: Any) -> None:
    """The Event log is append-only provenance. A purge neither deletes nor
    rewrites it; the outcome counts the references left behind so the residue
    is a reported fact, not a silent one."""
    world = scope_world
    run_a = await _expired_terminal_run(world, *world.a)
    run_b = await _expired_terminal_run(world, *world.b)
    event_a = await _event_for(world.events, world.a[0], run_a)
    await _event_for(world.events, world.b[0], run_b)

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    if world.backend == "memory":
        # The in-memory store owns no Event log; zero is the truthful report
        # of a boundary, not a stub.
        assert outcome.event_references_retained == 0
    else:
        assert outcome.event_references_retained == 1
    # Both events still resolve, whichever backend holds them.
    assert await world.events.get(event_a.event_id) is not None
    assert await world.runs.get_run(run_a.run_id) is None


# ── schedule claims: released with the Run, and only that one ─────


async def test_a_purged_run_releases_only_its_own_occurrence(scope_world: Any) -> None:
    from maistro.runs.sources import SCHEDULE_ID_KEY, SCHEDULED_FOR_KEY

    world = scope_world
    occurrences = {
        world.a[0]: ("schedule-a", "2026-08-01T00:00:00+00:00"),
        world.b[0]: ("schedule-b", "2026-08-01T00:00:00+00:00"),
    }
    for workspace, project_id in (world.a, world.b):
        schedule_id, scheduled_for = occurrences[workspace]
        run = await world.runs.create_run(
            _graph(workspace, project_id),
            provenance={
                SCHEDULE_ID_KEY: schedule_id,
                SCHEDULED_FOR_KEY: scheduled_for,
            },
            retention_expires_at=EXPIRED,
        )
        await world.runs.transition_run(run.run_id, RunStatus.QUEUED)
        await world.runs.transition_run(run.run_id, RunStatus.RUNNING)
        await world.runs.transition_run(run.run_id, RunStatus.COMPLETED)

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)
    assert outcome.schedule_claims_released == 1

    schedule_id, scheduled_for = occurrences[world.a[0]]
    # A's claim died with its Run: the firing can be admitted again.
    re_admitted = await world.runs.create_run(
        _graph(*world.a),
        provenance={SCHEDULE_ID_KEY: schedule_id, SCHEDULED_FOR_KEY: scheduled_for},
    )
    assert re_admitted.workspace_id == world.a[0]
    # B's claim is still held by its Run.
    with pytest.raises(DuplicateOccurrence):
        await world.runs.create_run(
            _graph(*world.b),
            provenance={
                SCHEDULE_ID_KEY: occurrences[world.b[0]][0],
                SCHEDULED_FOR_KEY: occurrences[world.b[0]][1],
            },
        )


# ── the global mode is explicit and attributed ────────────────────


async def test_a_global_sweep_is_explicit_and_touches_every_workspace(
    scope_world: Any,
) -> None:
    world = scope_world
    await _expired_terminal_run(world, *world.a)
    await _expired_terminal_run(world, *world.b)

    outcome = await world.runs.purge_expired_runs(
        GlobalRetentionScope(authorized_by="operator"), now=NOW
    )

    assert outcome.runs == 2
    assert outcome.is_global
    assert outcome.mode == "global"
    assert outcome.workspace_id is None
    assert await world.runs.list_by_status(RunStatus.COMPLETED) == []


def test_a_global_scope_names_its_principal() -> None:
    with pytest.raises(ValueError):
        GlobalRetentionScope(authorized_by="   ")


def test_a_workspace_scope_refuses_an_empty_workspace() -> None:
    with pytest.raises(ValueError):
        WorkspaceRetentionScope(workspace_id="")


# ── the backlog is a reported fact, not a guess ───────────────────


async def test_a_batch_limited_sweep_reports_its_backlog(scope_world: Any) -> None:
    world = scope_world
    for _ in range(3):
        await _expired_terminal_run(world, *world.a)

    first = await world.runs.purge_expired_runs(_scope_a(world), now=NOW, limit=2)
    assert first.runs == 2
    assert first.backlog_remaining is True

    second = await world.runs.purge_expired_runs(_scope_a(world), now=NOW, limit=2)
    assert second.runs == 1
    assert second.backlog_remaining is False


# ── concurrency: scopes partition the work ────────────────────────


async def test_concurrent_sweeps_of_different_scopes_never_cross(
    scope_world: Any,
) -> None:
    import asyncio

    world = scope_world
    for _ in range(2):
        await _expired_terminal_run(world, *world.a)
        await _expired_terminal_run(world, *world.b)

    scope_b = WorkspaceRetentionScope(workspace_id=world.b[0])
    outcome_a, outcome_b = await asyncio.gather(
        world.runs.purge_expired_runs(_scope_a(world), now=NOW, limit=2),
        world.runs.purge_expired_runs(scope_b, now=NOW, limit=2),
    )

    assert outcome_a.runs + outcome_b.runs == 4
    assert (await world.runs.purge_expired_runs(_scope_a(world), now=NOW)).runs == 0
