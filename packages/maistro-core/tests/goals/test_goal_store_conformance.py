"""One suite over all three Goal stores (#1572).

The in-memory store is the reference; SQLite and PostgreSQL are read against
it by running the same bodies. The PostgreSQL leg needs a migrated server and
skips without one; `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure in
the jobs that own a server.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from maistro.goals import (
    GoalLineageError,
    GoalNotFound,
    GoalRevisionConflict,
    GoalState,
    GoalTransitionRefused,
)
from maistro.testing.postgres import postgres_dsn


class _MemoryBackend:
    durable = False

    def __init__(self) -> None:
        from maistro.goals.store import InMemoryGoalStore
        from maistro.projects.scope_store import InMemoryProjectScopeStore

        self.project_store = InMemoryProjectScopeStore()
        self._store = InMemoryGoalStore(project_store=self.project_store)

    async def store(self):
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    durable = True

    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "goals.db"
        self._connections: list = []
        self.project_store = None

    async def store(self):
        import aiosqlite

        from maistro.goals.sqlite_store import SqliteGoalStore
        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        scope_store = SqliteProjectScopeStore(conn)
        await scope_store.ensure_schema()
        if self.project_store is None:
            self.project_store = scope_store
        store = SqliteGoalStore(conn, project_store=scope_store)
        await store.ensure_schema()
        return store

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    durable = True

    def __init__(self, pool) -> None:
        from maistro.projects.pg_scope_store import PgProjectScopeStore

        self._pool = pool
        self.project_store = PgProjectScopeStore(pool)

    async def store(self):
        from maistro.goals.pg_store import PgGoalStore

        return PgGoalStore(self._pool)

    async def close(self) -> None:
        return None


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(request, tmp_path):
    if request.param == "memory":
        yield _MemoryBackend()
        return
    if request.param == "sqlite":
        made = _SqliteBackend(tmp_path)
        await made.store()
        yield made
        await made.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL Goal-store leg cannot run and must not be silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    asyncpg = pytest.importorskip("asyncpg")
    # Two connections, so the concurrent-revise test is a real race rather than
    # one serialised by a single-connection pool.
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        yield _PostgresBackend(pool)
    finally:
        await pool.close()


def _id(label: str) -> str:
    """Unique per call: PostgreSQL keeps rows between tests and runs."""
    return f"{label}-{uuid4().hex}"


async def _root(backend, workspace_id: str | None = None):
    return await backend.project_store.create_root(workspace_id or _id("ws"))


async def _create(store, project, **overrides):
    kwargs = {
        "workspace_id": project.workspace_id,
        "project_id": project.project_id,
        "owner_agent_id": _id("agent"),
        "desired_state": "ship the release",
        "success_conditions": ("tests green", "tag pushed"),
        "stop_conditions": ("budget exhausted",),
        "author_principal_id": "user-a",
    }
    kwargs.update(overrides)
    return await store.create(**kwargs)


async def test_create_then_get_round_trips_goal_and_revision_one(backend) -> None:
    store = await backend.store()
    project = await _root(backend)

    goal, revision = await _create(store, project)

    assert goal.state is GoalState.ACTIVE
    assert goal.current_revision == 1
    assert goal.parent_goal_id is None
    assert revision.revision == 1
    assert revision.goal_id == goal.goal_id
    assert revision.owner_agent_id == goal.owner_agent_id

    reopened = await backend.store()
    assert await reopened.get(goal.goal_id) == goal
    assert await reopened.get_revision(goal.goal_id, 1) == revision
    assert await reopened.list_revisions(goal.goal_id) == [revision]
    assert revision.success_conditions == ("tests green", "tag pushed")
    assert revision.stop_conditions == ("budget exhausted",)
    assert goal.created_at.utcoffset() is not None


async def test_missing_goal_reads_as_absent(backend) -> None:
    store = await backend.store()

    assert await store.get(_id("goal")) is None
    assert await store.get_revision(_id("goal"), 1) is None
    assert await store.list_revisions(_id("goal")) == []


async def test_create_refuses_a_project_outside_the_workspace(backend) -> None:
    store = await backend.store()
    project = await _root(backend)

    with pytest.raises(GoalLineageError):
        await _create(store, project, workspace_id=_id("other-ws"))
    with pytest.raises(GoalLineageError):
        await _create(store, project, project_id=_id("missing-project"))


async def test_create_refuses_a_duplicate_goal_id(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    goal, _ = await _create(store, project)

    with pytest.raises(ValueError, match="already exists"):
        await _create(store, project, goal_id=goal.goal_id)


async def test_revise_appends_and_keeps_history(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    goal, first = await _create(store, project)

    second = await store.revise(
        goal.goal_id,
        expected_revision=1,
        desired_state="ship the release by Friday",
        success_conditions=("tag pushed",),
        stop_conditions=(),
        author_principal_id="user-b",
    )

    assert second.revision == 2
    assert second.owner_agent_id == goal.owner_agent_id
    reopened = await backend.store()
    current = await reopened.get(goal.goal_id)
    assert current is not None and current.current_revision == 2
    assert await reopened.list_revisions(goal.goal_id) == [first, second]
    assert await reopened.get_revision(goal.goal_id, 1) == first


async def test_stale_revise_is_refused(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    goal, _ = await _create(store, project)
    await store.revise(
        goal.goal_id,
        expected_revision=1,
        desired_state="v2",
        success_conditions=(),
        stop_conditions=(),
        author_principal_id="user-a",
    )

    with pytest.raises(GoalRevisionConflict):
        await store.revise(
            goal.goal_id,
            expected_revision=1,
            desired_state="stale",
            success_conditions=(),
            stop_conditions=(),
            author_principal_id="user-a",
        )
    assert len(await store.list_revisions(goal.goal_id)) == 2


async def test_revise_of_a_missing_goal_is_not_found(backend) -> None:
    store = await backend.store()

    with pytest.raises(GoalNotFound):
        await store.revise(
            _id("goal"),
            expected_revision=1,
            desired_state="x",
            success_conditions=(),
            stop_conditions=(),
            author_principal_id="user-a",
        )


async def test_concurrent_revises_have_exactly_one_winner(backend) -> None:
    project = await _root(backend)
    goal, _ = await _create(await backend.store(), project)
    writers = [await backend.store() for _ in range(2)]

    results = await asyncio.gather(
        *(
            writer.revise(
                goal.goal_id,
                expected_revision=1,
                desired_state=f"writer {index}",
                success_conditions=(),
                stop_conditions=(),
                author_principal_id=f"user-{index}",
            )
            for index, writer in enumerate(writers)
        ),
        return_exceptions=True,
    )

    winners = [item for item in results if not isinstance(item, BaseException)]
    losers = [item for item in results if isinstance(item, BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1 and isinstance(losers[0], GoalRevisionConflict)
    assert [item.revision for item in await writers[0].list_revisions(goal.goal_id)] == [1, 2]


async def test_transition_to_terminal_is_final(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    goal, _ = await _create(store, project)

    satisfied = await store.transition(
        goal.goal_id,
        expected_state=GoalState.ACTIVE,
        expected_revision=1,
        to_state=GoalState.SATISFIED,
    )

    assert satisfied.state is GoalState.SATISFIED
    assert satisfied.current_revision == 1
    reopened = await backend.store()
    assert (await reopened.get(goal.goal_id)) == satisfied
    with pytest.raises(GoalTransitionRefused):
        await reopened.transition(
            goal.goal_id,
            expected_state=GoalState.SATISFIED,
            expected_revision=1,
            to_state=GoalState.ACTIVE,
        )
    with pytest.raises(GoalTransitionRefused):
        await reopened.revise(
            goal.goal_id,
            expected_revision=1,
            desired_state="revive",
            success_conditions=(),
            stop_conditions=(),
            author_principal_id="user-a",
        )
    with pytest.raises(GoalTransitionRefused):
        await reopened.reassign_owner(
            goal.goal_id,
            expected_revision=1,
            owner_agent_id=_id("agent"),
            author_principal_id="user-a",
        )
    assert (await reopened.get(goal.goal_id)) == satisfied


async def test_transition_is_compare_and_set(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    goal, _ = await _create(store, project)
    await store.revise(
        goal.goal_id,
        expected_revision=1,
        desired_state="v2",
        success_conditions=(),
        stop_conditions=(),
        author_principal_id="user-a",
    )

    with pytest.raises(GoalRevisionConflict):
        await store.transition(
            goal.goal_id,
            expected_state=GoalState.ACTIVE,
            expected_revision=1,
            to_state=GoalState.CANCELLED,
        )
    with pytest.raises(GoalRevisionConflict):
        await store.transition(
            goal.goal_id,
            expected_state=GoalState.FAILED,
            expected_revision=2,
            to_state=GoalState.CANCELLED,
        )
    with pytest.raises(GoalTransitionRefused):
        await store.transition(
            goal.goal_id,
            expected_state=GoalState.ACTIVE,
            expected_revision=2,
            to_state=GoalState.ACTIVE,
        )
    with pytest.raises(GoalNotFound):
        await store.transition(
            _id("goal"),
            expected_state=GoalState.ACTIVE,
            expected_revision=1,
            to_state=GoalState.CANCELLED,
        )
    current = await store.get(goal.goal_id)
    assert current is not None and current.state is GoalState.ACTIVE


async def test_subgoal_keeps_lineage_within_its_project(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    parent, _ = await _create(store, project)

    child, _ = await _create(store, project, parent_goal_id=parent.goal_id)

    reopened = await backend.store()
    read = await reopened.get(child.goal_id)
    assert read is not None
    assert read.parent_goal_id == parent.goal_id
    assert read.project_id == parent.project_id
    listed = {
        item.goal_id
        for item in await reopened.list_for_project(project.workspace_id, project.project_id)
    }
    assert listed == {parent.goal_id, child.goal_id}


async def test_subgoal_with_a_parent_in_another_project_is_refused(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    other = await backend.project_store.create(
        workspace_id=project.workspace_id,
        name="other",
        parent_project_id=project.project_id,
    )
    parent, _ = await _create(store, project)

    with pytest.raises(GoalLineageError):
        await _create(store, other, parent_goal_id=parent.goal_id)
    with pytest.raises(GoalLineageError):
        await _create(store, project, parent_goal_id=_id("missing-goal"))
    assert await store.list_for_project(other.workspace_id, other.project_id) == []


async def test_list_owned_by_agent_returns_only_active_goals_of_that_agent(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    agent = _id("agent")
    active, _ = await _create(store, project, owner_agent_id=agent)
    done, _ = await _create(store, project, owner_agent_id=agent)
    await _create(store, project)
    await store.transition(
        done.goal_id,
        expected_state=GoalState.ACTIVE,
        expected_revision=1,
        to_state=GoalState.CANCELLED,
    )

    owned = await store.list_owned_by_agent(project.workspace_id, agent)

    assert [goal.goal_id for goal in owned] == [active.goal_id]
    assert await store.list_owned_by_agent(_id("ws"), agent) == []


async def test_reassign_owner_is_recorded_and_visible(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    first_owner = _id("agent")
    second_owner = _id("agent")
    goal, first = await _create(store, project, owner_agent_id=first_owner)

    change = await store.reassign_owner(
        goal.goal_id,
        expected_revision=1,
        owner_agent_id=second_owner,
        author_principal_id="user-admin",
    )

    assert change.revision == 2
    assert change.owner_agent_id == second_owner
    assert change.author_principal_id == "user-admin"
    assert change.desired_state == first.desired_state
    assert change.success_conditions == first.success_conditions
    reopened = await backend.store()
    current = await reopened.get(goal.goal_id)
    assert current is not None and current.owner_agent_id == second_owner
    history = await reopened.list_revisions(goal.goal_id)
    assert [item.owner_agent_id for item in history] == [first_owner, second_owner]
    assert await reopened.list_owned_by_agent(project.workspace_id, first_owner) == []
    assert [
        g.goal_id for g in await reopened.list_owned_by_agent(project.workspace_id, second_owner)
    ] == [goal.goal_id]
    with pytest.raises(GoalRevisionConflict):
        await reopened.reassign_owner(
            goal.goal_id,
            expected_revision=1,
            owner_agent_id=first_owner,
            author_principal_id="user-admin",
        )


async def test_a_terminal_goal_takes_no_subgoals(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    parent, _ = await _create(store, project)
    await store.transition(
        parent.goal_id,
        expected_state=GoalState.ACTIVE,
        expected_revision=1,
        to_state=GoalState.CANCELLED,
    )

    with pytest.raises(GoalTransitionRefused):
        await _create(store, project, parent_goal_id=parent.goal_id)
    assert [
        g.goal_id for g in await store.list_for_project(project.workspace_id, project.project_id)
    ] == [parent.goal_id]


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner_agent_id": " "},
        {"desired_state": ""},
        {"author_principal_id": ""},
        {"success_conditions": "tests green"},
        {"stop_conditions": ("",)},
    ],
)
async def test_blank_or_malformed_content_is_refused(backend, overrides) -> None:
    store = await backend.store()
    project = await _root(backend)

    with pytest.raises(ValueError):
        await _create(store, project, **overrides)
    assert await store.list_for_project(project.workspace_id, project.project_id) == []


async def test_reassigning_to_the_current_owner_is_refused(backend) -> None:
    store = await backend.store()
    project = await _root(backend)
    goal, _ = await _create(store, project)

    with pytest.raises(GoalTransitionRefused):
        await store.reassign_owner(
            goal.goal_id,
            expected_revision=1,
            owner_agent_id=goal.owner_agent_id,
            author_principal_id="user-a",
        )
    with pytest.raises(ValueError):
        await store.revise(
            goal.goal_id,
            expected_revision=1,
            desired_state=" ",
            success_conditions=(),
            stop_conditions=(),
            author_principal_id="user-a",
        )
    assert len(await store.list_revisions(goal.goal_id)) == 1


async def test_a_durable_project_with_goals_is_not_deleted_but_its_workspace_purge_takes_them(
    backend,
) -> None:
    """Explicit Project delete refuses to take append-only history with it.

    The in-memory Project store cannot see Goals, so there a delete leaves them
    readable rather than destroying them; the durable stores refuse.
    """
    from maistro.projects.scope import ProjectNotEmpty

    if not backend.durable:
        pytest.skip("the in-memory Project store has no view of Goals")
    store = await backend.store()
    root = await _root(backend)
    child = await backend.project_store.create(
        workspace_id=root.workspace_id, name="child", parent_project_id=root.project_id
    )
    goal, _ = await _create(store, child)

    with pytest.raises(ProjectNotEmpty, match="Goals"):
        await backend.project_store.delete(child.project_id)
    assert await store.get(goal.goal_id) == goal

    await backend.project_store.purge_workspace(root.workspace_id)

    assert await store.get(goal.goal_id) is None
    assert await store.list_revisions(goal.goal_id) == []
