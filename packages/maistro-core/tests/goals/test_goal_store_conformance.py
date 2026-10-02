"""One suite over every canonical Goal store: memory, SQLite, PostgreSQL (#1572).

Written as one suite from the start, for the reason the Project scope suite
was rewritten into one: two stores implementing one contract, with only one of
them tested, is how they come to disagree. The in-memory store is what the
Container wires with no durable substrate configured, so it is a real leg
rather than a convenience.

"Reopen" means a fresh store object on the same substrate -- a new connection
to the same SQLite file, a new store on the same pool. For the in-memory store
the object *is* the substrate, so the reopen assertions are trivially true
there: the honest weaker leg rather than a pretend durable one.

The PostgreSQL leg needs a real server and skips without one. A skipped leg is
untested, not passing; `MAISTRO_REQUIRE_PG_LEGS` turns the skip into a failure
in the jobs that own a server.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from maistro.goals.store import InMemoryGoalStore
from maistro.goals.types import (
    Goal,
    GoalLineageError,
    GoalNotFound,
    GoalRevision,
    GoalRevisionConflict,
    GoalState,
    GoalStateConflict,
)

WS = "ws-1"
OTHER_WS = "ws-2"
PROJECT = "project-1"
AGENT = "agent-1"


def _revision(goal_id: str, *, sequence: int = 1, desired: str = "ship the thing") -> GoalRevision:
    return GoalRevision(
        goal_id=goal_id,
        sequence=sequence,
        desired_state=desired,
        success_conditions=["the thing is shipped"],
        stop_conditions=["the thing is cancelled"],
        author_id="person-1",
    )


def _goal(
    revision: GoalRevision,
    *,
    workspace_id: str = WS,
    project_id: str = PROJECT,
    owner: str = AGENT,
    parent: str | None = None,
    created_at: datetime | None = None,
) -> Goal:
    return Goal(
        goal_id=revision.goal_id,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_agent_id=owner,
        parent_goal_id=parent,
        current_revision=revision.goal_revision,
        **({"created_at": created_at} if created_at else {}),
    )


class _MemoryBackend:
    """The store the Container wires with no durable substrate configured."""

    name = "memory"
    durable = False

    async def setup(self) -> None:
        self._store = InMemoryGoalStore()

    async def store(self):
        return self._store

    async def teardown(self) -> None:
        return None


class _SqliteBackend:
    name = "sqlite"
    durable = True

    def __init__(self, path) -> None:
        self._path = str(path)
        self._conns: list = []

    async def setup(self) -> None:
        store = await self.store()
        await store.ensure_schema()

    async def store(self):
        import aiosqlite

        from maistro.goals.sqlite_store import SqliteGoalStore

        conn = await aiosqlite.connect(self._path)
        self._conns.append(conn)
        return SqliteGoalStore(conn)

    async def teardown(self) -> None:
        for conn in self._conns:
            await conn.close()


@pytest.fixture(params=["memory", "sqlite"])
async def backend(request, tmp_path):
    made = (
        _MemoryBackend()
        if request.param == "memory"
        else _SqliteBackend(tmp_path / "goals.sqlite3")
    )
    await made.setup()
    try:
        yield made
    finally:
        await made.teardown()


@pytest.mark.asyncio
async def test_a_created_goal_reads_back_with_its_first_revision(backend) -> None:
    store = await backend.store()
    revision = _revision("g-create")
    await store.create(_goal(revision), revision)

    found = await store.get(WS, "g-create")
    assert found is not None
    assert found.current_revision == revision.goal_revision
    assert found.state is GoalState.ACTIVE
    assert [r.goal_revision for r in await store.revisions(WS, "g-create")] == [
        revision.goal_revision
    ]


@pytest.mark.asyncio
async def test_a_goal_in_another_workspace_is_indistinguishable_from_a_missing_one(
    backend,
) -> None:
    """#1150: "not yours" and "not there" must be one answer.

    Two different answers would make the error itself a roster: a caller could
    enumerate another Workspace's Goals by the shape of the refusal.
    """
    store = await backend.store()
    revision = _revision("g-foreign")
    await store.create(_goal(revision), revision)

    assert await store.get(OTHER_WS, "g-foreign") is None
    assert await store.get(WS, "g-does-not-exist") is None
    assert await store.revision(OTHER_WS, revision.goal_revision) is None

    with pytest.raises(GoalNotFound):
        await store.revisions(OTHER_WS, "g-foreign")


@pytest.mark.asyncio
async def test_revisions_are_append_only_and_move_the_pointer(backend) -> None:
    store = await backend.store()
    first = _revision("g-revise")
    await store.create(_goal(first), first)

    second = _revision("g-revise", sequence=2, desired="ship the better thing")
    updated = await store.revise(
        WS, "g-revise", expected_revision=first.goal_revision, revision=second
    )

    assert updated.current_revision == second.goal_revision
    history = await store.revisions(WS, "g-revise")
    assert [r.sequence for r in history] == [1, 2]
    assert [r.desired_state for r in history] == ["ship the thing", "ship the better thing"]

    # The superseded revision is still readable: a Run admitted against it
    # must be able to say what it was pursuing.
    carried = await store.revision(WS, first.goal_revision)
    assert carried is not None
    assert carried.desired_state == "ship the thing"


@pytest.mark.asyncio
async def test_a_stale_revision_pointer_loses(backend) -> None:
    store = await backend.store()
    first = _revision("g-stale")
    await store.create(_goal(first), first)
    second = _revision("g-stale", sequence=2, desired="second")
    await store.revise(WS, "g-stale", expected_revision=first.goal_revision, revision=second)

    with pytest.raises(GoalRevisionConflict):
        await store.revise(
            WS,
            "g-stale",
            expected_revision=first.goal_revision,
            revision=_revision("g-stale", sequence=3, desired="third"),
        )


@pytest.mark.asyncio
async def test_two_concurrent_revisions_have_exactly_one_winner(backend) -> None:
    """The normal case for #805, not an edge one: two reconcilers deciding at once."""
    store = await backend.store()
    first = _revision("g-race")
    await store.create(_goal(first), first)

    async def revise(desired: str):
        handle = await backend.store()
        return await handle.revise(
            WS,
            "g-race",
            expected_revision=first.goal_revision,
            revision=_revision("g-race", sequence=2, desired=desired),
        )

    results = await asyncio.gather(revise("a"), revise("b"), return_exceptions=True)
    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, GoalRevisionConflict)]

    assert len(winners) == 1, results
    assert len(losers) == 1, results
    assert len(await store.revisions(WS, "g-race")) == 2


@pytest.mark.asyncio
async def test_terminal_states_are_final(backend) -> None:
    store = await backend.store()
    revision = _revision("g-terminal")
    await store.create(_goal(revision), revision)

    await store.transition(
        WS, "g-terminal", expected_state=GoalState.ACTIVE, state=GoalState.SATISFIED
    )

    with pytest.raises(GoalStateConflict):
        await store.transition(
            WS, "g-terminal", expected_state=GoalState.SATISFIED, state=GoalState.ACTIVE
        )
    with pytest.raises(GoalStateConflict):
        await store.transition(
            WS, "g-terminal", expected_state=GoalState.SATISFIED, state=GoalState.FAILED
        )
    with pytest.raises(GoalStateConflict):
        await store.revise(
            WS,
            "g-terminal",
            expected_revision=revision.goal_revision,
            revision=_revision("g-terminal", sequence=2),
        )


@pytest.mark.asyncio
async def test_a_stale_state_loses(backend) -> None:
    store = await backend.store()
    revision = _revision("g-statecas")
    await store.create(_goal(revision), revision)

    with pytest.raises(GoalStateConflict):
        await store.transition(
            WS, "g-statecas", expected_state=GoalState.SATISFIED, state=GoalState.FAILED
        )


@pytest.mark.asyncio
async def test_ownership_moves_only_by_an_explicit_transition(backend) -> None:
    """Accountability is not part of what a Goal wants.

    Moving it must not require restating the desired outcome, and restating
    the outcome must not quietly move it.
    """
    store = await backend.store()
    revision = _revision("g-own")
    await store.create(_goal(revision), revision)

    moved = await store.reassign(WS, "g-own", expected_agent_id=AGENT, owner_agent_id="agent-2")
    assert moved.owner_agent_id == "agent-2"
    assert moved.current_revision == revision.goal_revision

    with pytest.raises(GoalStateConflict):
        await store.reassign(WS, "g-own", expected_agent_id=AGENT, owner_agent_id="agent-3")

    second = _revision("g-own", sequence=2, desired="restated")
    revised = await store.revise(
        WS, "g-own", expected_revision=revision.goal_revision, revision=second
    )
    assert revised.owner_agent_id == "agent-2"


@pytest.mark.asyncio
async def test_a_subgoal_keeps_its_parents_project(backend) -> None:
    store = await backend.store()
    parent_revision = _revision("g-parent")
    await store.create(_goal(parent_revision), parent_revision)

    child_revision = _revision("g-child")
    await store.create(_goal(child_revision, parent="g-parent"), child_revision)

    assert [c.goal_id for c in await store.children(WS, "g-parent")] == ["g-child"]

    stray = _revision("g-stray")
    with pytest.raises(GoalLineageError):
        await store.create(_goal(stray, parent="g-parent", project_id="project-2"), stray)

    orphan = _revision("g-orphan")
    with pytest.raises(GoalLineageError):
        await store.create(_goal(orphan, parent="g-nonexistent"), orphan)


@pytest.mark.asyncio
async def test_active_for_agent_is_what_a_waking_agent_enumerates(backend) -> None:
    """#805 AC-1: the Goals this Agent owns, without a chat session."""
    store = await backend.store()
    base = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

    for index, (goal_id, owner) in enumerate(
        [("g-a", AGENT), ("g-b", AGENT), ("g-other", "agent-9")]
    ):
        revision = _revision(goal_id)
        await store.create(
            _goal(revision, owner=owner, created_at=base + timedelta(minutes=index)), revision
        )

    done = _revision("g-done")
    await store.create(_goal(done, created_at=base + timedelta(minutes=3)), done)
    await store.transition(WS, "g-done", expected_state=GoalState.ACTIVE, state=GoalState.SATISFIED)

    assert [g.goal_id for g in await store.active_for_agent(WS, AGENT)] == ["g-a", "g-b"]
    assert [g.goal_id for g in await store.active_for_agent(WS, "agent-9")] == ["g-other"]
    assert await store.active_for_agent(OTHER_WS, AGENT) == []


@pytest.mark.asyncio
async def test_state_survives_the_object_that_wrote_it(backend) -> None:
    """Durability, stated as the question it actually asks."""
    store = await backend.store()
    first = _revision("g-durable")
    await store.create(_goal(first), first)
    second = _revision("g-durable", sequence=2, desired="after reopen")
    await store.revise(WS, "g-durable", expected_revision=first.goal_revision, revision=second)

    reopened = await backend.store()
    found = await reopened.get(WS, "g-durable")
    assert found is not None
    assert found.current_revision == second.goal_revision
    assert [r.sequence for r in await reopened.revisions(WS, "g-durable")] == [1, 2]


@pytest.mark.asyncio
async def test_a_duplicate_goal_id_is_refused(backend) -> None:
    store = await backend.store()
    revision = _revision("g-dup")
    await store.create(_goal(revision), revision)

    with pytest.raises(GoalRevisionConflict):
        again = _revision("g-dup", sequence=1, desired="second attempt")
        await store.create(_goal(again), again)


def test_the_postgres_leg_is_not_silently_absent() -> None:
    """A skipped leg is untested, not passing.

    This placeholder keeps the gap visible until `PgGoalStore` joins the
    parametrization; `MAISTRO_REQUIRE_PG_LEGS` makes its absence loud in the
    jobs that own a server.
    """
    if os.getenv("MAISTRO_REQUIRE_PG_LEGS"):
        pytest.fail("PostgreSQL leg is required in this job but not yet parametrized")
    pytest.skip("PgGoalStore leg lands with the PostgreSQL store")
