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
pre-#1175 unscoped purge. The dependent inventory is exercised, not
enumerated: a Schedule fire cursor is created per Workspace and the purge
must release exactly the cursor that named a purged Run — repointed, never
left dangling, and never taken from the other Workspace.
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
from maistro.privilege import PrivilegeGuard
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.retention_scope import (
    GlobalRetentionScope,
    WorkspaceRetentionScope,
)
from maistro.runs.sources import SCHEDULE_ID_KEY, SCHEDULED_FOR_KEY
from maistro.runs.store import DuplicateOccurrence, InMemoryRunStore
from maistro.scheduling.model import Schedule
from maistro.scheduling.store import InMemoryScheduleStore

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


async def _event_for(
    store: Any,
    workspace: str,
    run: Any,
    *,
    reference: dict[str, str] | None = None,
) -> EventEnvelope:
    return await store.append(
        EventEnvelope(
            type="run.completed",
            workspace_id=workspace,
            project_id=run.project_id,
            payload={"run_id": run.run_id},
            **(reference or {"run_id": run.run_id}),
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
        # The migrated database owns `graph_continuations` (migration 021); the
        # purge reaches it through its own SQL, and this handle is how the test
        # proves the row actually went — the same read-back the sqlite leg does
        # against its own continuation store.
        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore

        # Bare `return` after the yield, never `return <value>`: a fixture
        # that yields anywhere is an async generator, and a valued return
        # from one is a SyntaxError. Each branch yields exactly once and
        # returns, so no leg falls through into another's setup.
        from maistro.scheduling.pg_store import PgScheduleStore

        schedules = PgScheduleStore(pg_pool)
        yield SimpleNamespace(
            backend="postgres",
            runs=PgRunStore(pg_pool, project_store=projects),
            continuations=PgGraphContinuationStore(pg_pool),
            events=events,
            schedules=schedules,
            a=scoped["a"],
            b=scoped["b"],
        )
        return

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
        continuations = InMemoryGraphContinuationStore()
        schedules = InMemoryScheduleStore()
        yield SimpleNamespace(
            backend="memory",
            runs=InMemoryRunStore(
                project_store=projects,
                continuation_store=continuations,
                # The same object the purge releases schedule cursors
                # through: held here so the cursor tests can read back what
                # the sweep repointed.
                schedule_store=schedules,
            ),
            # The same object the purge reclaims through: held here so the
            # continuation tests can read back what the sweep deleted.
            continuations=continuations,
            schedules=schedules,
            events=InMemoryEventStore(),
            a=scoped["a"],
            b=scoped["b"],
        )
        return

    conn = await aiosqlite.connect(":memory:")
    from maistro.runs.sqlite_store import SqliteRunStore

    run_store = SqliteRunStore(conn, project_store=projects)
    await run_store.ensure_schema()
    continuations = SqliteGraphContinuationStore(conn)
    await continuations.ensure_schema()
    from maistro.events.envelope import SqliteEventStore
    from maistro.scheduling.store import SqliteScheduleStore

    events = SqliteEventStore(conn)
    await events.ensure_schema()
    schedules = SqliteScheduleStore(conn)
    await schedules.ensure_schema()
    # The connection must be closed on teardown: aiosqlite runs its driver on
    # a non-daemon thread, and an open connection would keep the test process
    # alive after the suite finished.
    try:
        yield SimpleNamespace(
            backend="sqlite",
            runs=run_store,
            continuations=continuations,
            events=events,
            schedules=schedules,
            a=scoped["a"],
            b=scoped["b"],
        )
    finally:
        await conn.close()


def _continuation_store_or_skip(world: Any) -> Any:
    """The continuation store a test can read, on every leg.

    Every leg wires one: memory and sqlite hold the same object the run
    store's purge seam reclaims, and the postgres leg reads the migrated
    `graph_continuations` table the purge deletes from directly. A leg
    without a readable handle would make the continuation-purge assertion
    a skip — and a skip proves nothing about whether the dependent row
    actually went (#1175).
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
    rewrites it; the outcome counts references through any execution id so the
    residue is a reported fact, not a silent one."""
    world = scope_world
    run_a = await _expired_terminal_run(world, *world.a)
    run_b = await _expired_terminal_run(world, *world.b)
    node_run = (await world.runs.list_node_runs(run_a.run_id))[0]
    attempt = (await world.runs.list_attempts(node_run.node_run_id))[0]
    events = [
        await _event_for(world.events, world.a[0], run_a, reference={"run_id": run_a.run_id}),
        await _event_for(
            world.events,
            world.a[0],
            run_a,
            reference={"node_run_id": node_run.node_run_id},
        ),
        await _event_for(
            world.events,
            world.a[0],
            run_a,
            reference={"attempt_id": attempt.attempt_id},
        ),
    ]
    await _event_for(world.events, world.b[0], run_b)

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    if world.backend == "memory":
        # The in-memory store owns no Event log; zero is the truthful report
        # of a boundary, not a stub.
        assert outcome.event_references_retained == 0
    else:
        assert outcome.event_references_retained == 3
    # All events still resolve, whichever backend holds them.
    for event in events:
        assert await world.events.get(event.event_id) is not None
    assert await world.runs.get_run(run_a.run_id) is None


# ── schedule claims: released with the Run, and only that one ─────


@pytest.mark.parametrize(
    "provenance",
    [
        {SCHEDULE_ID_KEY: "partial"},
        {SCHEDULED_FOR_KEY: "2026-08-01T00:00:00+00:00"},
    ],
)
async def test_a_partial_schedule_provenance_does_not_count_as_an_occurrence(
    scope_world: Any,
    provenance: dict[str, str],
) -> None:
    """Only a complete `(schedule_id, scheduled_for)` pair is an occurrence
    claim. A purge must not report a partial provenance row as a released
    claim, including on the PostgreSQL backend that projects provenance."""
    world = scope_world
    valid = await world.runs.create_run(
        _graph(*world.a),
        provenance={
            SCHEDULE_ID_KEY: "schedule-a",
            SCHEDULED_FOR_KEY: "2026-08-01T00:00:00+00:00",
        },
        retention_expires_at=EXPIRED,
    )
    await world.runs.transition_run(valid.run_id, RunStatus.QUEUED)
    await world.runs.transition_run(valid.run_id, RunStatus.RUNNING)
    await world.runs.transition_run(valid.run_id, RunStatus.COMPLETED)
    partial = await world.runs.create_run(
        _graph(*world.a),
        provenance=provenance,
        retention_expires_at=EXPIRED,
    )
    await world.runs.transition_run(partial.run_id, RunStatus.QUEUED)
    await world.runs.transition_run(partial.run_id, RunStatus.RUNNING)
    await world.runs.transition_run(partial.run_id, RunStatus.COMPLETED)
    partial_twin = await world.runs.create_run(
        _graph(*world.a),
        provenance=provenance,
        retention_expires_at=EXPIRED,
    )
    await world.runs.transition_run(partial_twin.run_id, RunStatus.QUEUED)
    await world.runs.transition_run(partial_twin.run_id, RunStatus.RUNNING)
    await world.runs.transition_run(partial_twin.run_id, RunStatus.COMPLETED)

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    assert outcome.runs == 3
    assert outcome.schedule_claims_released == 1
    # The two partial rows coexist because neither half-key is a claim; only
    # the complete row contributes to the released-claim count.


async def test_a_purged_run_releases_only_its_own_occurrence(scope_world: Any) -> None:
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


# ── schedule cursors: a pointer to the newest Run, released, not dangling ──


async def test_a_purged_run_releases_the_schedule_cursor_that_named_it(
    scope_world: Any,
) -> None:
    """`Schedule.last_run_id` points at the newest Run; when retention deletes
    that Run the pointer must be repointed — released, never left as a broken
    id — and only in the purged Workspace. The fire history (`last_fired_at`,
    `runs_so_far`) is attribution, not a pointer, and survives intact."""
    world = scope_world
    run_a = await _expired_terminal_run(world, *world.a)
    run_b = await _expired_terminal_run(world, *world.b)
    schedules: dict[str, Schedule] = {}
    for name, (workspace, project_id), run in (
        ("a", world.a, run_a),
        ("b", world.b, run_b),
    ):
        schedule = await world.schedules.put(
            Schedule(
                workspace_id=workspace,
                project_id=project_id,
                name=f"cursor-{name}",
                cron="* * * * *",
                graph_template_id="template-1",
            )
        )
        # Advance the cursor exactly the way a real firing does, so the test
        # exercises the same pointer the engine stamps.
        await world.schedules.record_fire(
            schedule.schedule_id,
            fired_at=NOW - timedelta(minutes=1),
            run_id=run.run_id,
            next_due_at=NOW,
        )
        schedules[name] = schedule

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    assert outcome.schedule_pointers_released == 1
    cursor_a = await world.schedules.get(schedules["a"].schedule_id)
    assert cursor_a is not None
    # Released, not dangling: the cursor no longer names the purged Run.
    assert cursor_a.last_run_id is None
    # The fire history is not the pointer, and is not touched.
    assert cursor_a.last_fired_at is not None
    assert cursor_a.runs_so_far == 1
    # B's cursor is untouched: its Run still exists to be named.
    cursor_b = await world.schedules.get(schedules["b"].schedule_id)
    assert cursor_b is not None
    assert cursor_b.last_run_id == run_b.run_id


async def test_a_schedule_cursor_is_only_released_by_its_own_scope(
    scope_world: Any,
) -> None:
    """The release is scope-discovered, not store-wide: A's purge repoints
    only cursors naming A's purged Runs, even though B's expired Run names a
    cursor too. (The B Run survives the sweep; its cursor must survive with
    it, or the release would be a second, unscoped purge in miniature.)"""
    world = scope_world
    run_b = await _expired_terminal_run(world, *world.b)
    schedule_b = await world.schedules.put(
        Schedule(
            workspace_id=world.b[0],
            project_id=world.b[1],
            name="cursor-b",
            cron="* * * * *",
            graph_template_id="template-1",
        )
    )
    await world.schedules.record_fire(
        schedule_b.schedule_id,
        fired_at=NOW - timedelta(minutes=1),
        run_id=run_b.run_id,
        next_due_at=NOW,
    )

    outcome = await world.runs.purge_expired_runs(_scope_a(world), now=NOW)

    assert outcome.schedule_pointers_released == 0
    cursor_b = await world.schedules.get(schedule_b.schedule_id)
    assert cursor_b is not None
    assert cursor_b.last_run_id == run_b.run_id


# ── the global mode is explicit and attributed ────────────────────


async def test_a_global_sweep_is_explicit_and_touches_every_workspace(
    scope_world: Any, tmp_path: Any
) -> None:
    world = scope_world
    await _expired_terminal_run(world, *world.a)
    await _expired_terminal_run(world, *world.b)

    guard = PrivilegeGuard(data_dir=tmp_path)
    guard.initialize(admin_public_key="pk_admin", user_public_key="pk_user")
    outcome = await world.runs.purge_expired_runs(
        GlobalRetentionScope(guard.issue_global_retention_grant("pk_admin")), now=NOW
    )

    assert outcome.runs == 2
    assert outcome.is_global
    assert outcome.mode == "global"
    assert outcome.workspace_id is None
    assert await world.runs.list_by_status(RunStatus.COMPLETED) == []


def test_a_global_scope_requires_an_authority_capability() -> None:
    with pytest.raises(TypeError, match="PrivilegeGuard-issued grant"):
        GlobalRetentionScope("operator")  # type: ignore[arg-type]


def test_a_global_grant_is_revoked_when_the_admin_key_rotates(tmp_path: Any) -> None:
    guard = PrivilegeGuard(data_dir=tmp_path)
    guard.initialize(admin_public_key="pk_admin", user_public_key="pk_user")
    scope = GlobalRetentionScope(guard.issue_global_retention_grant("pk_admin"))
    guard.rotate_admin_key("pk_admin", "pk_admin-v2")

    with pytest.raises(PermissionError, match="no longer valid"):
        scope.grant.validate()


async def test_an_invalid_runtime_scope_is_rejected(scope_world: Any) -> None:
    with pytest.raises(TypeError, match="requires WorkspaceRetentionScope"):
        await scope_world.runs.purge_expired_runs(None, now=NOW)  # type: ignore[arg-type]


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


# ── a failed purge commits no partial deletion ─────────────────


async def test_an_aborted_purge_commits_no_partial_deletion(monkeypatch: Any) -> None:
    """The SQLite purge is one transaction or it did not happen (#1175).

    The purge runs on a connection shared with every other write the store
    makes, so a failure midway must roll back before raising — otherwise the
    next unrelated write commits the sweep's half-done deletes as a passenger:
    an apparently successful mutation carrying a deletion nobody reported.
    The failure is injected after the continuation delete, the exact point
    where an earlier revision of this purge left a Run whose continuation was
    gone once any later write landed.
    """
    conn = await aiosqlite.connect(":memory:")
    try:
        from maistro.runs.sqlite_store import SqliteRunStore

        projects = InMemoryProjectScopeStore()
        root = await projects.create_root(WORKSPACE_A)
        project = await projects.create(
            workspace_id=WORKSPACE_A,
            parent_project_id=root.project_id,
            name="Scoped",
        )
        store = SqliteRunStore(conn, project_store=projects)
        await store.ensure_schema()
        continuations = SqliteGraphContinuationStore(conn)
        await continuations.ensure_schema()

        run = await store.create_run(
            _graph(WORKSPACE_A, project.project_id), retention_expires_at=EXPIRED
        )
        await store.transition_run(run.run_id, RunStatus.QUEUED)
        await store.transition_run(run.run_id, RunStatus.RUNNING)
        await store.transition_run(run.run_id, RunStatus.COMPLETED)
        await _continuation_for(continuations, run)

        async def explode(_run_id_param: str) -> int:
            raise RuntimeError("injected failure after the continuation delete")

        monkeypatch.setattr(store, "_count_retained_references", explode)
        with pytest.raises(RuntimeError, match="injected failure"):
            await store.purge_expired_runs(
                WorkspaceRetentionScope(workspace_id=WORKSPACE_A), now=NOW
            )

        # A later, successful write on the same connection must not commit
        # the aborted sweep's deletes: the Run and its continuation both
        # still resolve, and the new Run is durable.
        survivor = await store.create_run(_graph(WORKSPACE_A, project.project_id))
        assert await store.get_run(run.run_id) is not None
        assert await continuations.get(run.run_id) is not None
        assert await store.get_run(survivor.run_id) is not None
    finally:
        await conn.close()
