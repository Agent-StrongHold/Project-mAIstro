"""One suite over all three Goal stores (#1572).

`InMemoryGoalStore` is the reference — the definition of the contract. The
SQLite and PostgreSQL twins agree with it only if the same bodies pass over
all three, so the suite below is deliberately one file with one parametrized
fixture: running the reference in it is what makes "the durable stores behave
like the reference" a comparison rather than an assertion.

The acceptance criteria this suite holds every backend to (issue #1572):

* **Round-trip.** A Goal, its revision chain and its recorded transitions
  survive a close-and-reopen of the durable substrate with the exact values
  they were written with.
* **Append-only revisions with one CAS winner.** A stale `expected_revision`
  is refused; two concurrent appends produce exactly one winner, one new
  revision, and an intact chain; earlier revisions are never rewritten.
* **Subgoal lineage.** A parent must exist in the same Workspace *and*
  Project; the child carries both forward; the parent is untouched by the
  child's mutations.
* **Recorded ownership change.** Reassigning the accountable Agent is its own
  transition record carrying both owners and the actor; a no-op reassignment
  is refused.
* **Terminal states are final.** No transition out of a terminal state, and
  no mutation of a terminal Goal, on any backend.
* **Authorization (foreign = missing).** Two principals in two Workspaces
  cannot read or mutate each other's Goals, and a foreign Goal raises the
  same one refusal a missing Goal does — driven through `ScopedGoalStore`,
  the shipped seam, not by poking the raw store.

The PostgreSQL leg needs a real migrated server and skips without one, and a
skipped leg is untested rather than passing: `MAISTRO_REQUIRE_PG_LEGS` turns
that skip into a failure in the jobs that own a server. Migration ``058``
owns the PostgreSQL tables; the SQLite twin carries its own DDL, and
`test_goal_schema_parity.py` holds the two descriptions to one spec.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from maistro.goals import (
    TERMINAL_GOAL_STATUSES,
    Goal,
    GoalNotVisible,
    GoalRevisionConflict,
    GoalRevisionDraft,
    GoalStatus,
    GoalTransitionError,
    GoalTransitionKind,
    InMemoryGoalStore,
    ScopedGoalStore,
)
from maistro.goals.model import GoalNotFound, GoalParentInvalid
from maistro.testing.postgres import postgres_dsn

_PRINCIPAL = "principal-goals-conformance"


class _MemoryBackend:
    """The reference. One store object for the whole leg: an in-memory store
    *is* its own substrate, so a fresh instance would share nothing and the
    reopen assertions would be vacuously true."""

    durable = False

    def __init__(self) -> None:
        self._store = InMemoryGoalStore()

    async def store(self):
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    """A file on disk; each `store()` reopens the database from scratch, so
    the round-trip legs prove durability and not just dictionary behavior."""

    durable = True

    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "goals.db"
        self._connections: list = []

    async def store(self):
        import aiosqlite

        from maistro.goals.sqlite_store import SqliteGoalStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        store = SqliteGoalStore(conn)
        await store.ensure_schema()
        return store

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    """A migrated database; every `store()` is a fresh object on one pool."""

    durable = True

    def __init__(self, pool) -> None:
        self._pool = pool

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
        yield made
        await made.close()
        return
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL Goal-store leg cannot run and must not be "
                "silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4)
    try:
        yield _PostgresBackend(pool)
    finally:
        await pool.close()


def _draft(state: str = "the workspace README reflects the new layout", author: str = "agent-7"):
    return GoalRevisionDraft(
        desired_state=state,
        success_conditions=("review approved",),
        stop_conditions=("two consecutive failed verifications",),
        author=author,
    )


async def _goal(backend, *, workspace_id: str = "ws-1", project_id: str = "prj-1", **kwargs: Any):
    store = await backend.store()
    return await store.create_goal(
        workspace_id=workspace_id,
        project_id=project_id,
        agent_id="agent-7",
        draft=_draft(),
        **kwargs,
    )


async def test_goal_round_trips_through_the_backend(backend) -> None:
    """Create, reopen, read back: the Goal, its revision and its history are
    the records that were written, not similar ones."""
    created = await _goal(backend, parent_goal_id=None)
    read_back = await (await backend.store()).get_goal(created.goal_id)
    assert read_back == created
    assert read_back is not None
    store = await backend.store()
    assert await store.list_goal_revisions(created.goal_id) == [
        await _first_revision(store, created.goal_id)
    ]
    assert await store.list_goal_transitions(created.goal_id) == []
    # The revision content itself survives: desired state, conditions, author.
    revisions = await store.list_goal_revisions(created.goal_id)
    assert revisions[0].desired_state == _draft().desired_state
    assert revisions[0].success_conditions == ("review approved",)
    assert revisions[0].stop_conditions == ("two consecutive failed verifications",)
    assert revisions[0].author == "agent-7"
    assert revisions[0].revision == 1


async def _first_revision(store, goal_id: str):
    revisions = await store.list_goal_revisions(goal_id)
    return revisions[0]


async def test_goal_revision_chain_is_append_only_with_one_cas_winner(backend) -> None:
    store = await backend.store()
    goal = await _goal(backend)

    # The current revision moves; the chain only grows; revision 1 is frozen.
    updated = await store.append_revision(goal.goal_id, _draft("state two"), expected_revision=1)
    assert updated.current_revision == 2
    chain = await store.list_goal_revisions(goal.goal_id)
    assert [revision.revision for revision in chain] == [1, 2]
    assert chain[0].desired_state == _draft().desired_state, "revision 1 was rewritten"

    # A stale pointer is refused, and refusing writes nothing.
    with pytest.raises(GoalRevisionConflict):
        await store.append_revision(goal.goal_id, _draft("stale"), expected_revision=1)
    assert len(await store.list_goal_revisions(goal.goal_id)) == 2

    # Two concurrent appends from the same pointer: exactly one winner.
    results = await asyncio.gather(
        store.append_revision(goal.goal_id, _draft("racer A"), expected_revision=2),
        store.append_revision(goal.goal_id, _draft("racer B"), expected_revision=2),
        return_exceptions=True,
    )
    won = [r for r in results if not isinstance(r, BaseException)]
    lost = [r for r in results if isinstance(r, BaseException)]
    assert len(won) == 1, f"exactly one concurrent append may win, got {len(won)}"
    assert len(lost) == 1 and isinstance(lost[0], GoalRevisionConflict)
    assert won[0].current_revision == 3
    chain = await store.list_goal_revisions(goal.goal_id)
    assert [revision.revision for revision in chain] == [1, 2, 3]
    assert chain[2].desired_state in {"racer A", "racer B"}


async def test_lifecycle_transitions_cas_and_terminal_is_final(backend) -> None:
    store = await backend.store()
    goal = await _goal(backend)

    # CAS: a stale revision refuses the transition too.
    with pytest.raises(GoalRevisionConflict):
        await store.transition_goal(
            goal.goal_id, GoalStatus.CANCELLED, expected_revision=9, actor=_PRINCIPAL
        )
    assert (await store.get_goal(goal.goal_id)).status is GoalStatus.ACTIVE

    moved = await store.transition_goal(
        goal.goal_id, GoalStatus.SATISFIED, expected_revision=1, actor=_PRINCIPAL
    )
    assert moved.status is GoalStatus.SATISFIED
    records = await store.list_goal_transitions(goal.goal_id)
    assert len(records) == 1
    assert records[0].actor == _PRINCIPAL
    assert records[0].from_status is GoalStatus.ACTIVE
    assert records[0].to_status is GoalStatus.SATISFIED

    # Terminal is final: no transition out, and no mutation at all.
    for target in GoalStatus:
        with pytest.raises(GoalTransitionError):
            await store.transition_goal(
                goal.goal_id, target, expected_revision=moved.current_revision, actor=_PRINCIPAL
            )
    with pytest.raises(GoalTransitionError):
        await store.append_revision(
            goal.goal_id, _draft("too late"), expected_revision=moved.current_revision
        )
    with pytest.raises(GoalTransitionError):
        await store.reassign_agent(
            goal.goal_id,
            "agent-8",
            expected_revision=moved.current_revision,
            actor=_PRINCIPAL,
        )
    # And every terminal state refuses equally — walk one Goal per state so
    # the loop above is not only exercising `satisfied`.
    for terminal in sorted(TERMINAL_GOAL_STATUSES, key=str):
        other = await _goal(backend)
        await store.transition_goal(other.goal_id, terminal, expected_revision=1, actor=_PRINCIPAL)
        with pytest.raises(GoalTransitionError):
            await store.transition_goal(
                other.goal_id, GoalStatus.ACTIVE, expected_revision=1, actor=_PRINCIPAL
            )


async def test_concurrent_transitions_have_exactly_one_winner(backend) -> None:
    store = await backend.store()
    goal = await _goal(backend)
    results = await asyncio.gather(
        store.transition_goal(goal.goal_id, GoalStatus.SATISFIED, expected_revision=1, actor="a"),
        store.transition_goal(goal.goal_id, GoalStatus.CANCELLED, expected_revision=1, actor="b"),
        return_exceptions=True,
    )
    won = [r for r in results if not isinstance(r, BaseException)]
    lost = [r for r in results if isinstance(r, BaseException)]
    assert len(won) == 1 and len(lost) == 1
    final = await store.get_goal(goal.goal_id)
    assert final.status in {GoalStatus.SATISFIED, GoalStatus.CANCELLED}
    assert len(await store.list_goal_transitions(goal.goal_id)) == 1


async def test_subgoal_lineage_preserves_parent_goal_and_project(backend) -> None:
    store = await backend.store()
    parent = await _goal(backend, workspace_id="ws-1", project_id="prj-1")
    child = await _goal(
        backend,
        workspace_id="ws-1",
        project_id="prj-1",
        parent_goal_id=parent.goal_id,
    )
    assert child.parent_goal_id == parent.goal_id
    assert (child.workspace_id, child.project_id) == (parent.workspace_id, parent.project_id)

    # Lineage never crosses a scope boundary: missing parent, foreign
    # Workspace, foreign Project.
    for kwargs in (
        {"workspace_id": "ws-1", "project_id": "prj-1", "parent_goal_id": "goal-does-not-exist"},
        {"workspace_id": "ws-2", "project_id": "prj-1", "parent_goal_id": parent.goal_id},
        {"workspace_id": "ws-1", "project_id": "prj-9", "parent_goal_id": parent.goal_id},
    ):
        with pytest.raises(GoalParentInvalid):
            await store.create_goal(
                workspace_id=kwargs["workspace_id"],
                project_id=kwargs["project_id"],
                agent_id="agent-7",
                draft=_draft(),
                parent_goal_id=kwargs["parent_goal_id"],
            )

    # A child mutating itself leaves the parent exactly where it was.
    before = await store.get_goal(parent.goal_id)
    await store.append_revision(child.goal_id, _draft("child moves"), expected_revision=1)
    await store.transition_goal(
        child.goal_id, GoalStatus.SATISFIED, expected_revision=2, actor=_PRINCIPAL
    )
    after = await store.get_goal(parent.goal_id)
    assert after == before
    assert after.status is GoalStatus.ACTIVE


async def test_agent_reassignment_is_an_explicit_recorded_transition(backend) -> None:
    store = await backend.store()
    goal = await _goal(backend)

    with pytest.raises(GoalTransitionError):
        await store.reassign_agent(goal.goal_id, "agent-7", expected_revision=1, actor=_PRINCIPAL)

    reassigned = await store.reassign_agent(
        goal.goal_id, "agent-8", expected_revision=1, actor=_PRINCIPAL
    )
    assert reassigned.agent_id == "agent-8"
    assert reassigned.current_revision == 1, "ownership moves without burning a revision"
    records = await store.list_goal_transitions(goal.goal_id)
    assert len(records) == 1
    assert records[0].from_agent_id == "agent-7"
    assert records[0].to_agent_id == "agent-8"
    assert records[0].actor == _PRINCIPAL


async def test_missing_goal_is_goal_not_found_on_every_read(backend) -> None:
    store = await backend.store()
    assert await store.get_goal("goal-absent") is None
    with pytest.raises(GoalNotFound):
        await store.list_goal_revisions("goal-absent")
    with pytest.raises(GoalNotFound):
        await store.list_goal_transitions("goal-absent")


#
# The authorization seam. Driven against every backend's store so the
# refusal shape does not depend on which substrate is underneath.
#


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def scoped(request, tmp_path):
    """A ScopedGoalStore over the backend's store, with two Workspaces and
    one member principal each."""
    if request.param == "memory":
        made = _MemoryBackend()
    elif request.param == "sqlite":
        made = _SqliteBackend(tmp_path)
    else:
        dsn = postgres_dsn()
        if not dsn:
            if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
                raise RuntimeError(
                    "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty"
                )
            pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
        asyncpg = pytest.importorskip("asyncpg")
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        made = _PostgresBackend(pool)
    try:
        from maistro.workspaces.store import InMemoryWorkspaceStore

        store = await made.store()
        workspace_store = InMemoryWorkspaceStore()
        await workspace_store.create(creator_user_id="alice", name="Alpha", workspace_id="ws-1")
        await workspace_store.create(creator_user_id="bob", name="Beta", workspace_id="ws-2")
        yield store, ScopedGoalStore(store, workspace_store)
    finally:
        await made.close()


async def test_two_principals_cannot_reach_each_other_s_goals(scoped) -> None:
    store, seam = scoped
    goal = await store.create_goal(
        workspace_id="ws-1",
        project_id="prj-1",
        agent_id="agent-7",
        draft=_draft(),
    )
    other = await store.create_goal(
        workspace_id="ws-2",
        project_id="prj-1",
        agent_id="agent-7",
        draft=_draft(),
    )

    # Alice owns a membership in ws-1 only; bob in ws-2 only.
    assert await seam.get_goal(goal.goal_id, principal_id="alice") == goal
    assert await seam.get_goal(other.goal_id, principal_id="bob") == other
    for principal, target in (("bob", goal.goal_id), ("alice", other.goal_id), ("", goal.goal_id)):
        with pytest.raises(GoalNotVisible):
            await seam.get_goal(target, principal_id=principal)

    # Reads of the chain refuse the same way.
    for principal, target in (("bob", goal.goal_id), ("alice", other.goal_id)):
        with pytest.raises(GoalNotVisible):
            await seam.list_goal_revisions(target, principal_id=principal)
        with pytest.raises(GoalNotVisible):
            await seam.list_goal_transitions(target, principal_id=principal)

    # So do all mutations — including ones the raw store would accept.
    with pytest.raises(GoalNotVisible):
        await seam.append_revision(
            goal.goal_id, _draft("bob was here"), principal_id="bob", expected_revision=1
        )
    with pytest.raises(GoalNotVisible):
        await seam.transition_goal(
            goal.goal_id,
            GoalStatus.CANCELLED,
            principal_id="bob",
            expected_revision=1,
            actor="bob",
        )
    with pytest.raises(GoalNotVisible):
        await seam.reassign_agent(
            goal.goal_id,
            "agent-9",
            principal_id="bob",
            expected_revision=1,
            actor="bob",
        )
    # Nothing was written by any refused call.
    assert (await store.get_goal(goal.goal_id)).current_revision == 1
    assert (await store.get_goal(goal.goal_id)).agent_id == "agent-7"
    assert await store.list_goal_transitions(goal.goal_id) == []

    # A non-member cannot create into a Workspace either, and a member can.
    with pytest.raises(GoalNotVisible):
        await seam.create_goal(
            principal_id="bob",
            workspace_id="ws-1",
            project_id="prj-1",
            agent_id="agent-7",
            draft=_draft(),
        )
    created = await seam.create_goal(
        principal_id="alice",
        workspace_id="ws-1",
        project_id="prj-1",
        agent_id="agent-7",
        draft=_draft(),
    )
    assert isinstance(created, Goal)


async def test_a_foreign_goal_answers_exactly_like_a_missing_one(scoped) -> None:
    """One refusal, one message, for absent, foreign and blank principal.

    "Indistinguishable" is a property of the answer, so the test compares the
    exceptions the seam actually raises — type and string — not the intent in
    its docstring.
    """
    store, seam = scoped
    goal = await store.create_goal(
        workspace_id="ws-1",
        project_id="prj-1",
        agent_id="agent-7",
        draft=_draft(),
    )
    missing = await _refusal_of(seam.get_goal("goal-absent", principal_id="alice"))
    foreign = await _refusal_of(seam.get_goal(goal.goal_id, principal_id="bob"))
    blank = await _refusal_of(seam.get_goal("goal-absent", principal_id="  "))
    assert type(missing) is type(foreign) is type(blank) is GoalNotVisible
    assert str(missing) == str(foreign) == str(blank)

    # Same for a mutation: bob cannot tell that alice's goal id exists.
    mutate_missing = await _refusal_of(
        seam.transition_goal(
            "goal-absent",
            GoalStatus.CANCELLED,
            principal_id="alice",
            expected_revision=1,
            actor="alice",
        )
    )
    mutate_foreign = await _refusal_of(
        seam.transition_goal(
            goal.goal_id,
            GoalStatus.CANCELLED,
            principal_id="bob",
            expected_revision=1,
            actor="bob",
        )
    )
    assert type(mutate_missing) is type(mutate_foreign) is GoalNotVisible
    assert str(mutate_missing) == str(mutate_foreign)


async def test_an_authorized_member_drives_every_seam_path(scoped) -> None:
    """Membership is enough: the seam's write paths and chain reads answer a
    member exactly as the raw store would, with the CAS expectation travelling
    with each call. The refusals are proven by the isolation tests above; this
    is the other half — that authorization gates the calls instead of
    replacing them."""
    _store, seam = scoped
    goal = await seam.create_goal(
        principal_id="alice",
        workspace_id="ws-1",
        project_id="prj-1",
        agent_id="agent-7",
        draft=_draft(),
    )

    revised = await seam.append_revision(
        goal.goal_id,
        _draft("v2"),
        principal_id="alice",
        expected_revision=1,
    )
    assert revised.current_revision == 2
    assert await seam.get_goal(goal.goal_id, principal_id="alice") == revised

    # A stale expectation is the store's own CAS refusal, passed through —
    # the seam decides *whether* a principal may write, never *what*.
    with pytest.raises(GoalRevisionConflict):
        await seam.append_revision(
            goal.goal_id,
            _draft("stale"),
            principal_id="alice",
            expected_revision=1,
        )

    reassigned = await seam.reassign_agent(
        goal.goal_id,
        "agent-9",
        principal_id="alice",
        expected_revision=2,
        actor="alice",
    )
    assert reassigned.agent_id == "agent-9"

    satisfied = await seam.transition_goal(
        goal.goal_id,
        GoalStatus.SATISFIED,
        principal_id="alice",
        expected_revision=2,
        actor="alice",
    )
    assert satisfied.status is GoalStatus.SATISFIED

    # The chain reads answer the member with the store's own records.
    revisions = await seam.list_goal_revisions(goal.goal_id, principal_id="alice")
    assert [revision.revision for revision in revisions] == [1, 2]
    transitions = await seam.list_goal_transitions(goal.goal_id, principal_id="alice")
    assert {record.kind for record in transitions} == {
        GoalTransitionKind.AGENT_REASSIGN,
        GoalTransitionKind.STATUS,
    }


async def test_a_substrate_lookup_failure_is_the_one_refusal(scoped) -> None:
    """``get_goal`` may legally answer a missing id with ``None`` or with a
    ``LookupError`` (every shipped store answers ``None``; the protocol
    allows both). The seam converts either into the one :class:`GoalNotVisible`
    — a substrate's refusal shape must not leak into a caller's hands as a
    different exception for the same invisible Goal."""
    _store, seam = scoped

    class RaisingStore(InMemoryGoalStore):
        async def get_goal(self, goal_id: str) -> Goal | None:
            raise GoalNotFound(goal_id)

    raiser = ScopedGoalStore(RaisingStore(), seam.workspace_store)
    refused = await _refusal_of(raiser.get_goal("goal-absent", principal_id="alice"))
    assert type(refused) is GoalNotVisible


async def _refusal_of(awaitable):
    try:
        await awaitable
    except GoalNotVisible as refused:
        return refused
    raise AssertionError("expected GoalNotVisible")
