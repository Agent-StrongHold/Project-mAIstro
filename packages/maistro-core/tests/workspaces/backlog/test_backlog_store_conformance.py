"""One suite over the in-memory and SQLite BacklogItem stores (#98, #100).

The in-memory store is the reference; running the same bodies against the
SQLite store is what makes "the durable store behaves like the reference" a
comparison. Both are paired with a real Project scope store, because the
Project check is part of the contract, not something a fake could stand in for.

The claim bodies (#100) inject the clock (`at`) wherever lease expiry matters,
so the tests assert the store's deterministic policy rather than racing a wall
clock: expiry is a reading the store is given, not a timer it owns.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces.backlog import (
    BacklogClaim,
    BacklogClaimHeld,
    BacklogClaimRefused,
    BacklogItem,
    BacklogItemAlreadyExists,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogRelationError,
    BacklogStaleFence,
    BacklogVersionConflict,
    GoalReference,
)
from maistro.workspaces.campaigns.model import AutonomyMode


class _MemoryBackend:
    def __init__(self) -> None:
        from maistro.workspaces.backlog.store import InMemoryBacklogItemStore

        self.projects = InMemoryProjectScopeStore()
        self._store = InMemoryBacklogItemStore(project_store=self.projects)

    async def store(self):
        return self._store

    async def close(self) -> None:
        return None


class _SqliteBackend:
    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "backlog.db"
        self._connections: list = []
        self.projects = None

    async def store(self):
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
        from maistro.workspaces.backlog.sqlite_store import SqliteBacklogItemStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        self.projects = SqliteProjectScopeStore(conn)
        await self.projects.ensure_schema()
        store = SqliteBacklogItemStore(conn, project_store=self.projects)
        await store.ensure_schema()
        return store

    async def reopen(self):
        for conn in self._connections:
            await conn.close()
        self._connections.clear()
        return await self.store()

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


@pytest.fixture(params=["memory", "sqlite"])
async def backend(request, tmp_path):
    made = _MemoryBackend() if request.param == "memory" else _SqliteBackend(tmp_path)
    try:
        yield made
    finally:
        await made.close()


async def _workspace(backend, store, workspace_id: str) -> str:
    """A Workspace's Root Project, on the store's own Project backend."""
    del store
    root = await backend.projects.create_root(workspace_id)
    return root.project_id


def _item(workspace_id: str, project_id: str, **fields) -> BacklogItem:
    return BacklogItem(workspace_id=workspace_id, project_id=project_id, title="Do it", **fields)


async def test_create_get_round_trip(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = _item(
        "ws-a",
        project_id,
        external_key="engine-001",
        status=BacklogItemStatus.ACCEPTED,
        acceptance_refs=["AC-1"],
        allowed_scope=["packages/maistro-core"],
        autonomy_mode="supervised",
        rank=2.5,
        goal_ref=GoalReference(goal_id="g-1", goal_revision="r7"),
    )

    created = await store.create(item)

    assert created.version == 1
    assert await store.get(item.item_id) == created
    assert await store.get("missing") is None


async def test_duplicate_external_key_in_one_workspace_is_refused(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    await store.create(_item("ws-a", project_id, external_key="engine-001"))

    with pytest.raises(BacklogItemAlreadyExists):
        await store.create(_item("ws-a", project_id, external_key="engine-001"))


async def test_duplicate_item_id_is_refused(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(BacklogItemAlreadyExists):
        await store.create(item)


async def test_list_filters_by_project_and_status_in_rank_order(backend) -> None:
    store = await backend.store()
    root_id = await _workspace(backend, store, "ws-a")
    child = await backend.projects.create(
        workspace_id="ws-a", parent_project_id=root_id, name="Child"
    )
    other_root = await _workspace(backend, store, "ws-b")
    low = await store.create(_item("ws-a", root_id, rank=2.0))
    high = await store.create(_item("ws-a", root_id, rank=1.0))
    blocked = await store.create(
        _item("ws-a", child.project_id, rank=0.0, status=BacklogItemStatus.BLOCKED)
    )
    await store.create(_item("ws-b", other_root))

    listed = await store.list("ws-a")
    assert [item.item_id for item in listed] == [blocked.item_id, high.item_id, low.item_id]
    by_project = await store.list("ws-a", project_id=root_id)
    assert [item.item_id for item in by_project] == [high.item_id, low.item_id]
    by_status = await store.list("ws-a", status=BacklogItemStatus.BLOCKED)
    assert [item.item_id for item in by_status] == [blocked.item_id]


async def test_update_is_compare_and_set(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    updated = await store.update(
        item.item_id, expected_version=1, changes={"title": "Renamed", "paused": True}
    )
    assert (updated.version, updated.title, updated.paused) == (2, "Renamed", True)
    assert updated.updated_at >= item.updated_at

    with pytest.raises(BacklogVersionConflict) as caught:
        await store.update(item.item_id, expected_version=1, changes={"title": "Stale"})
    assert caught.value.expected == 1
    assert caught.value.current_item == updated
    assert await store.get(item.item_id) == updated


async def test_version_conflict_payload_is_a_detached_copy(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(BacklogVersionConflict) as caught:
        await store.update(item.item_id, expected_version=99, changes={"title": "Stale"})

    caught.value.current_item.title = "Mutated by a caller, not through compare-and-set"
    refetched = await store.get(item.item_id)
    assert refetched.title == item.title
    assert refetched.version == item.version


async def test_update_refuses_identity_and_claim_fields(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    for field, value in (
        ("workspace_id", "ws-b"),
        ("version", 9),
        ("parent_item_id", "x"),
        ("fence_token", 1),
    ):
        with pytest.raises(ValueError, match=field):
            await store.update(item.item_id, expected_version=1, changes={field: value})
    with pytest.raises(ValidationError):
        await store.update(item.item_id, expected_version=1, changes={"not_a_field": 1})
    assert await store.get(item.item_id) == item


async def test_update_missing_item_raises_not_found(backend) -> None:
    store = await backend.store()

    with pytest.raises(BacklogItemNotFound):
        await store.update("missing", expected_version=1, changes={"title": "x"})


async def test_concurrent_updates_with_one_version_have_one_winner(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    results = await asyncio.gather(
        store.update(item.item_id, expected_version=1, changes={"title": "UI"}),
        store.update(item.item_id, expected_version=1, changes={"title": "Agent"}),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, BacklogItem)]
    losers = [result for result in results if isinstance(result, BacklogVersionConflict)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].current_item == winners[0]
    assert await store.get(item.item_id) == winners[0]


async def test_update_to_project_in_another_workspace_is_refused(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    foreign = await _workspace(backend, store, "ws-b")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(BacklogRelationError) as caught:
        await store.update(item.item_id, expected_version=1, changes={"project_id": foreign})
    assert caught.value.kind == "cross_workspace"
    assert await store.get(item.item_id) == item


async def test_create_in_project_of_another_workspace_is_refused(backend) -> None:
    store = await backend.store()
    await _workspace(backend, store, "ws-a")
    foreign = await _workspace(backend, store, "ws-b")

    for project_id in (foreign, "no-such-project"):
        with pytest.raises(BacklogRelationError) as caught:
            await store.create(_item("ws-a", project_id))
        assert caught.value.kind == "cross_workspace"
    assert await store.list("ws-a") == []


async def test_dependencies_are_structured_and_acyclic(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    a = await store.create(_item("ws-a", project_id, rank=1))
    b = await store.create(_item("ws-a", project_id, rank=2))
    c = await store.create(_item("ws-a", project_id, rank=3))

    await store.add_dependency(a.item_id, b.item_id)
    await store.add_dependency(b.item_id, c.item_id)
    await store.add_dependency(a.item_id, b.item_id)

    assert [i.item_id for i in await store.dependencies_of(a.item_id)] == [b.item_id]
    assert [i.item_id for i in await store.dependents_of(b.item_id)] == [a.item_id]

    with pytest.raises(BacklogRelationError) as self_edge:
        await store.add_dependency(a.item_id, a.item_id)
    assert self_edge.value.kind == "self"
    with pytest.raises(BacklogRelationError) as cycle:
        await store.add_dependency(c.item_id, a.item_id)
    assert cycle.value.kind == "cycle"
    assert await store.dependencies_of(c.item_id) == []

    await store.remove_dependency(a.item_id, b.item_id)
    assert await store.dependencies_of(a.item_id) == []
    await store.add_dependency(c.item_id, a.item_id)
    assert [i.item_id for i in await store.dependencies_of(c.item_id)] == [a.item_id]


async def test_dependency_on_missing_item_raises_not_found(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    a = await store.create(_item("ws-a", project_id))

    with pytest.raises(BacklogItemNotFound):
        await store.add_dependency(a.item_id, "missing")
    with pytest.raises(BacklogItemNotFound):
        await store.dependencies_of("missing")


async def test_cross_workspace_dependency_and_parent_are_refused(backend) -> None:
    store = await backend.store()
    a_project = await _workspace(backend, store, "ws-a")
    b_project = await _workspace(backend, store, "ws-b")
    a = await store.create(_item("ws-a", a_project))
    b = await store.create(_item("ws-b", b_project))

    with pytest.raises(BacklogRelationError) as dependency:
        await store.add_dependency(a.item_id, b.item_id)
    assert dependency.value.kind == "cross_workspace"
    with pytest.raises(BacklogRelationError) as parent:
        await store.set_parent(a.item_id, b.item_id, expected_version=1)
    assert parent.value.kind == "cross_workspace"
    with pytest.raises(BacklogRelationError):
        await store.create(_item("ws-a", a_project, parent_item_id=b.item_id))
    assert await store.get(a.item_id) == a


async def test_parent_links_are_versioned_and_acyclic(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    root = await store.create(_item("ws-a", project_id, rank=1))
    child = await store.create(_item("ws-a", project_id, rank=2, parent_item_id=root.item_id))
    grandchild = await store.create(_item("ws-a", project_id, rank=3))

    moved = await store.set_parent(grandchild.item_id, child.item_id, expected_version=1)
    assert (moved.parent_item_id, moved.version) == (child.item_id, 2)
    assert [i.item_id for i in await store.children_of(root.item_id)] == [child.item_id]
    assert [i.item_id for i in await store.children_of(child.item_id)] == [grandchild.item_id]

    with pytest.raises(BacklogRelationError) as cycle:
        await store.set_parent(root.item_id, grandchild.item_id, expected_version=1)
    assert cycle.value.kind == "cycle"
    with pytest.raises(BacklogRelationError) as self_edge:
        await store.set_parent(root.item_id, root.item_id, expected_version=1)
    assert self_edge.value.kind == "self"
    with pytest.raises(BacklogVersionConflict):
        await store.set_parent(grandchild.item_id, None, expected_version=1)

    detached = await store.set_parent(grandchild.item_id, None, expected_version=2)
    assert (detached.parent_item_id, detached.version) == (None, 3)
    assert await store.children_of(child.item_id) == []


async def test_set_parent_checks_version_before_the_requested_parent(backend) -> None:
    """A stale expected_version must win over an invalid parent (#98 review).

    Checking the parent first would surface a relation/not-found error and
    hide the version conflict, so a caller racing another writer could not
    tell "rebase me" apart from "that parent is wrong" and would retry with
    the wrong fix.
    """
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(BacklogVersionConflict):
        await store.set_parent(item.item_id, "does-not-exist", expected_version=99)
    with pytest.raises(BacklogVersionConflict):
        await store.set_parent(item.item_id, item.item_id, expected_version=99)


async def test_sqlite_restart_keeps_item_edges_and_version(tmp_path) -> None:
    """Durability is the SQLite store's alone: the reference has no restart."""
    backend = _SqliteBackend(tmp_path)
    try:
        await _restart_round_trip(backend)
    finally:
        await backend.close()


async def _restart_round_trip(backend: _SqliteBackend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    parent = await store.create(_item("ws-a", project_id, rank=1))
    item = await store.create(
        _item(
            "ws-a",
            project_id,
            rank=2,
            parent_item_id=parent.item_id,
            goal_ref=GoalReference(goal_id="g-1", goal_revision=3),
        )
    )
    await store.add_dependency(item.item_id, parent.item_id)
    item = await store.update(item.item_id, expected_version=1, changes={"title": "Kept"})

    reopened = await backend.reopen()

    assert await reopened.get(item.item_id) == item
    assert (await reopened.get(item.item_id)).version == 2
    assert [i.item_id for i in await reopened.dependencies_of(item.item_id)] == [parent.item_id]
    assert [i.item_id for i in await reopened.children_of(parent.item_id)] == [item.item_id]
    assert (await reopened.get(item.item_id)).goal_ref == GoalReference(
        goal_id="g-1", goal_revision=3
    )


def test_goal_ref_keeps_exact_identity_and_revision() -> None:
    by_string = GoalReference(goal_id="g-1", goal_revision="7")
    by_int = GoalReference(goal_id="g-1", goal_revision=7)
    assert by_string.goal_revision == "7"
    assert by_int.goal_revision == 7
    assert GoalReference.model_validate_json(by_string.model_dump_json()) == by_string
    assert GoalReference.model_validate_json(by_int.model_dump_json()) == by_int


@pytest.mark.parametrize(
    "payload",
    [
        {"goal_id": "g-1"},
        {"goal_id": "g-1", "goal_revision": ""},
        {"goal_id": "g-1", "goal_revision": "  "},
        {"goal_id": "g-1", "goal_revision": 0},
        {"goal_id": "g-1", "goal_revision": True},
        {"goal_id": " ", "goal_revision": "1"},
        {"goal_id": "g-1", "goal_revision": "1", "desired_outcome": "ship it"},
    ],
)
def test_goal_ref_rejects_missing_blank_or_outcome_fields(payload) -> None:
    with pytest.raises(ValidationError):
        GoalReference.model_validate(payload)


async def test_update_to_a_taken_external_key_is_refused(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    await store.create(_item("ws-a", project_id, external_key="engine-001"))
    other = await store.create(_item("ws-a", project_id, external_key="engine-002"))

    with pytest.raises(BacklogItemAlreadyExists):
        await store.update(
            other.item_id, expected_version=1, changes={"external_key": "engine-001"}
        )
    assert await store.get(other.item_id) == other


async def test_diamond_dependencies_are_not_a_cycle(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    top, left, right, bottom, extra = [
        await store.create(_item("ws-a", project_id, rank=n)) for n in range(5)
    ]
    for item, target in ((top, left), (top, right), (left, bottom), (right, bottom)):
        await store.add_dependency(item.item_id, target.item_id)

    await store.add_dependency(extra.item_id, top.item_id)

    with pytest.raises(BacklogRelationError):
        await store.add_dependency(bottom.item_id, extra.item_id)
    assert [i.item_id for i in await store.dependents_of(bottom.item_id)] == [
        left.item_id,
        right.item_id,
    ]


async def test_sqlite_compare_and_set_miss_reports_the_current_item(tmp_path) -> None:
    """The `WHERE version = ?` is the last word, not the read before it: a
    writer that slips in between (another process on the file) loses there."""
    backend = _SqliteBackend(tmp_path)
    try:
        store = await backend.store()
        project_id = await _workspace(backend, store, "ws-a")
        item = await store.create(_item("ws-a", project_id))
        current = await store.update(item.item_id, expected_version=1, changes={"title": "Won"})

        async with backend.projects.transaction() as conn:
            with pytest.raises(BacklogVersionConflict) as caught:
                await store._compare_and_set(
                    conn, item.model_copy(update={"version": 2}), expected_version=1
                )
        assert caught.value.current_item == current
    finally:
        await backend.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "  "},
        {"project_id": ""},
        {"item_id": "same", "parent_item_id": "same"},
    ],
)
def test_backlog_item_rejects_blank_identity_and_self_parent(fields) -> None:
    payload = {"workspace_id": "ws-a", "project_id": "p", "title": "t", **fields}
    with pytest.raises(ValidationError):
        BacklogItem(**payload)


def test_backlog_item_reads_naive_timestamps_as_utc() -> None:
    from datetime import UTC, datetime

    item = BacklogItem(
        workspace_id="ws-a",
        project_id="p",
        title="t",
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    assert item.created_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("rank", [float("inf"), float("-inf"), float("nan")])
async def test_non_finite_rank_is_refused_and_leaves_the_row_readable(backend, rank) -> None:
    """A rank the payload cannot round-trip (JSON has no inf/nan) must never be
    written: a stored ``null`` rank made every read of the Workspace fail."""
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(ValidationError):
        await store.update(item.item_id, expected_version=1, changes={"rank": rank})
    with pytest.raises(ValidationError):
        _item("ws-a", project_id, rank=rank)
    assert await store.list("ws-a") == [item]


async def test_create_refuses_claim_fields(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")

    with pytest.raises(ValueError, match="fence_token"):
        await store.create(_item("ws-a", project_id, fence_token=3))
    assert await store.list("ws-a") == []


async def test_returned_items_are_not_the_stored_record(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    snapshot = item.model_copy(deep=True)
    item.pinned = True

    fetched = await store.get(item.item_id)
    fetched.title = "mutated without a version bump"
    (await store.list("ws-a"))[0].acceptance_refs.append("sneaky")

    assert await store.get(item.item_id) == snapshot


def test_backlog_item_normalises_aware_timestamps_to_utc() -> None:
    from datetime import UTC, datetime, timedelta, timezone

    item = BacklogItem(
        workspace_id="ws-a",
        project_id="p",
        title="t",
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2))),
    )
    assert item.created_at.tzinfo is UTC
    assert item.created_at == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


# -- claims: atomic take, explicit lease, fencing (#100) ----------------------


def _at(*, offset: float = 0.0) -> datetime:
    """A real-now base, so live-by-real-clock and injected readings agree:
    claims taken at `_at()` are active for the rest of the test, while expiry
    and hand-off are exercised through readings placed deliberately later."""
    return datetime.now(UTC) + timedelta(seconds=offset)


async def test_claim_is_atomic_and_records_the_claimant(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(
        _item("ws-a", project_id, goal_ref=GoalReference(goal_id="g-1", goal_revision="r7"))
    )
    at = _at()

    winner, loser = await asyncio.gather(
        store.claim(
            item.item_id, principal_id="human-1", agent_id="agent-7", run_id="run-1", at=at
        ),
        store.claim(item.item_id, principal_id="human-2", at=at),
        return_exceptions=True,
    )

    assert isinstance(winner, BacklogItem)
    assert isinstance(loser, BacklogClaimHeld)
    assert (winner.claimant_principal_id, winner.claimant_agent_id, winner.claim_run_id) == (
        "human-1",
        "agent-7",
        "run-1",
    )
    assert winner.fence_token == 1
    assert winner.version == item.version + 1
    assert winner.lease_expires_at > at
    assert winner.goal_ref == GoalReference(goal_id="g-1", goal_revision="r7")
    assert await store.get(item.item_id) == winner
    assert loser.claim.fence_token == winner.fence_token
    assert loser.current_item == winner


async def test_expired_lease_reopens_the_item_and_a_reclaim_advances_the_fence(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    claimed = await store.claim(item.item_id, principal_id="first", at=_at())

    assert await store.active_claim(item.item_id, at=claimed.lease_expires_at) is None
    second = await store.claim(
        item.item_id, agent_id="agent-9", at=claimed.lease_expires_at + timedelta(seconds=1)
    )
    assert second.fence_token == claimed.fence_token + 1
    assert second.claimant_principal_id is None

    # The first holder's receipt is dead: no renew, no release, no edit.
    stale_fence = claimed.fence_token
    with pytest.raises(BacklogStaleFence) as renew:
        await store.renew_claim(item.item_id, fence_token=stale_fence, lease_seconds=100)
    assert renew.value.current_item == second
    with pytest.raises(BacklogStaleFence):
        await store.release_claim(item.item_id, fence_token=stale_fence)
    with pytest.raises(BacklogStaleFence):
        await store.update(
            item.item_id,
            expected_version=second.version,
            changes={"status": "implemented"},
            fence_token=stale_fence,
        )
    assert await store.get(item.item_id) == second


async def test_renew_extends_the_lease_without_moving_the_generation(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    at = _at()
    claimed = await store.claim(item.item_id, principal_id="holder", at=at, lease_seconds=100)

    renewed = await store.renew_claim(
        item.item_id,
        fence_token=claimed.fence_token,
        lease_seconds=500,
        at=at + timedelta(seconds=10),
    )

    assert renewed.fence_token == claimed.fence_token
    assert renewed.lease_expires_at == at + timedelta(seconds=510)
    assert renewed.version == claimed.version + 1
    with pytest.raises(BacklogStaleFence):
        await store.renew_claim(
            item.item_id, fence_token=claimed.fence_token + 1, lease_seconds=500
        )


async def test_renew_and_release_refuse_a_non_holder_at_the_live_fence(backend) -> None:
    """The fence is readable by every contributor, so it alone proves nothing:
    renew/release must also match the authenticated principal to the holder."""
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    claimed = await store.claim(item.item_id, principal_id="holder", at=_at())
    live_fence = claimed.fence_token

    with pytest.raises(BacklogClaimRefused) as renew:
        await store.renew_claim(
            item.item_id,
            principal_id="impostor",
            fence_token=live_fence,
            lease_seconds=100,
        )
    assert "not the claim holder" in renew.value.reason
    with pytest.raises(BacklogClaimRefused) as release:
        await store.release_claim(item.item_id, principal_id="impostor", fence_token=live_fence)
    assert "not the claim holder" in release.value.reason
    assert await store.get(item.item_id) == claimed

    # The real holder still renews and releases at the same fence.
    renewed = await store.renew_claim(
        item.item_id, principal_id="holder", fence_token=live_fence, lease_seconds=100
    )
    assert renewed.fence_token == live_fence
    released = await store.release_claim(item.item_id, principal_id="holder", fence_token=live_fence)
    assert released.claimant_principal_id is None


async def test_release_clears_the_claim_and_the_fence_never_repeats(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    claimed = await store.claim(item.item_id, principal_id="holder", at=_at())

    released = await store.release_claim(item.item_id, fence_token=claimed.fence_token)

    assert (released.claimant_principal_id, released.lease_expires_at) == (None, None)
    assert released.fence_token == claimed.fence_token + 1
    assert await store.active_claim(item.item_id) is None
    with pytest.raises(BacklogClaimRefused) as again:
        await store.release_claim(item.item_id, fence_token=released.fence_token)
    assert "no active claim" in again.value.reason

    # A later claim advances the counter again: receipt 1 can never open it.
    retaken = await store.claim(item.item_id, principal_id="next")
    assert retaken.fence_token == released.fence_token + 1


@pytest.mark.parametrize(
    "status,satisfied",
    [
        *[(s, False) for s in ("proposed", "accepted", "accepted_spec", "blocked", "abandoned")],
        *[(s, True) for s in ("implemented", "superseded", "obsolete")],
    ],
)
async def test_claim_waits_for_satisfied_dependencies(backend, status, satisfied) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    dependency = await store.create(
        _item("ws-a", project_id, rank=1, status=BacklogItemStatus(status))
    )
    item = await store.create(_item("ws-a", project_id, rank=2))
    await store.add_dependency(item.item_id, dependency.item_id)

    if satisfied:
        claimed = await store.claim(item.item_id, principal_id="worker")
        assert claimed.claimant_principal_id == "worker"
    else:
        with pytest.raises(BacklogClaimRefused) as refused:
            await store.claim(item.item_id, principal_id="worker")
        assert dependency.item_id in refused.value.reason
        assert await store.active_claim(item.item_id) is None


@pytest.mark.parametrize(
    "status,claimable",
    [
        *[(s, True) for s in ("proposed", "accepted", "accepted_spec")],
        *[(s, False) for s in ("blocked", "implemented", "superseded", "obsolete", "abandoned")],
    ],
)
async def test_claim_only_from_the_claimable_status_pool(backend, status, claimable) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id, status=BacklogItemStatus(status)))

    if claimable:
        assert (await store.claim(item.item_id, principal_id="worker")).claimant_principal_id
    else:
        with pytest.raises(BacklogClaimRefused) as refused:
            await store.claim(item.item_id, principal_id="worker")
        assert status in refused.value.reason


def test_agent_claimable_autonomy_modes_are_the_campaign_vocabulary_minus_human_only() -> None:
    """The claim gate's mode literals must not drift from #103's enum."""
    from maistro.workspaces.backlog.model import AGENT_CLAIMABLE_AUTONOMY_MODES

    assert (
        {mode.value for mode in AutonomyMode} - {AutonomyMode.HUMAN_ONLY.value}
    ) == AGENT_CLAIMABLE_AUTONOMY_MODES


@pytest.mark.parametrize(
    "autonomy_mode,agent_claim,claim_succeeds",
    [
        (None, True, True),
        (AutonomyMode.AUTONOMOUS.value, True, True),
        (AutonomyMode.AUTONOMOUS_WITH_PROMOTION_APPROVAL.value, True, True),
        (AutonomyMode.HUMAN_REVIEW_REQUIRED.value, True, True),
        (AutonomyMode.HUMAN_ONLY.value, True, False),
        (AutonomyMode.HUMAN_ONLY.value, False, True),
        ("experimental-something", True, False),
        ("experimental-something", False, True),
    ],
)
async def test_agent_claims_respect_the_autonomy_mode(
    backend, autonomy_mode, agent_claim, claim_succeeds
) -> None:
    """`human-only` and every unrecognized token refuse Agent claims: an
    unknown constraint is a constraint, not a permission. Human claims are
    never autonomy-gated."""
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id, autonomy_mode=autonomy_mode))

    if agent_claim:
        if claim_succeeds:
            claimed = await store.claim(item.item_id, agent_id="agent-1")
            assert claimed.claimant_agent_id == "agent-1"
        else:
            with pytest.raises(BacklogClaimRefused) as refused:
                await store.claim(item.item_id, agent_id="agent-1")
            assert "autonomy mode" in refused.value.reason
    elif claim_succeeds:
        claimed = await store.claim(item.item_id, principal_id="human-1")
        assert claimed.claimant_principal_id == "human-1"
    else:
        pytest.fail("human claims are never autonomy-refused")


async def test_declared_scope_is_checked_against_allowed_and_protected(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(
        _item("ws-a", project_id, allowed_scope=["packages/"], protected_scope=["deploy/"])
    )

    # Refusals run against the unclaimed item: the held-claim gate is checked
    # first by design, so a refused declaration never displaces a live claim.
    with pytest.raises(BacklogClaimRefused) as protected:
        await store.claim(item.item_id, principal_id="worker", scope=("deploy/prod.yml",))
    assert "protected scope" in protected.value.reason
    with pytest.raises(BacklogClaimRefused) as outside:
        await store.claim(item.item_id, principal_id="worker", scope=("frontend/app.ts",))
    assert "allowed scope" in outside.value.reason
    # '..' survives PurePosixPath untouched, so boundary comparison alone
    # would call packages/../deploy/prod.yml allowed-scope-inside and
    # protected-scope-outside; traversal segments are refused outright.
    with pytest.raises(BacklogClaimRefused) as traversal:
        await store.claim(
            item.item_id, principal_id="worker", scope=("packages/../deploy/prod.yml",)
        )
    assert "'..' path segments" in traversal.value.reason
    assert await store.active_claim(item.item_id) is None

    inside = await store.claim(
        item.item_id, principal_id="worker", scope=("packages/maistro-core/src/x.py",)
    )
    assert inside.claimant_principal_id == "worker"
    # The claim itself carried a declaration; giving it up and re-claiming
    # without one succeeds, and the fence advanced twice (release, then claim).
    released = await store.release_claim(item.item_id, fence_token=inside.fence_token)
    undeclared = await store.claim(item.item_id, agent_id="agent-1")
    assert undeclared.fence_token == released.fence_token + 1


async def test_claimed_items_edit_only_under_the_live_fence(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    claimed = await store.claim(item.item_id, principal_id="holder", at=_at())
    del claimed

    with pytest.raises(BacklogStaleFence):
        await store.update(item.item_id, expected_version=item.version + 1, changes={"title": "x"})
    with pytest.raises(BacklogStaleFence):
        await store.update(
            item.item_id,
            expected_version=item.version + 1,
            changes={"title": "x"},
            fence_token=99,
        )
    edited = await store.update(
        item.item_id,
        expected_version=item.version + 1,
        changes={"title": "holder edit"},
        fence_token=1,
    )
    assert edited.title == "holder edit"

    # Released: the item is unclaimed work again, editable without a fence.
    released = await store.release_claim(item.item_id, fence_token=1)
    reopened = await store.update(
        item.item_id, expected_version=released.version, changes={"title": "anyone"}
    )
    assert reopened.title == "anyone"


async def test_a_stale_holder_cannot_edit_after_the_fence_moves(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    first = await store.claim(item.item_id, principal_id="first", at=_at())
    await store.release_claim(item.item_id, fence_token=first.fence_token)
    second = await store.claim(item.item_id, agent_id="agent-9")

    with pytest.raises(BacklogStaleFence) as refused:
        await store.update(
            item.item_id,
            expected_version=second.version,
            changes={"status": "implemented"},
            fence_token=first.fence_token,
        )
    assert refused.value.current_item == second
    assert await store.get(item.item_id) == second


async def test_retiring_a_claimed_item_releases_the_claim_in_the_same_write(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))
    claimed = await store.claim(item.item_id, principal_id="holder", at=_at())

    retired = await store.update(
        item.item_id,
        expected_version=claimed.version,
        changes={"status": "abandoned"},
        fence_token=claimed.fence_token,
    )

    assert retired.status is BacklogItemStatus.ABANDONED
    assert (retired.claimant_principal_id, retired.lease_expires_at) == (None, None)
    assert await store.active_claim(item.item_id) is None
    # Deterministic re-eligibility: back into the pool, then claimable again.
    reopened = await store.update(
        item.item_id, expected_version=retired.version, changes={"status": "accepted"}
    )
    again = await store.claim(item.item_id, agent_id="agent-2")
    assert again.version == reopened.version + 1
    assert again.claimant_agent_id == "agent-2"
    # The fence advanced on retirement, so the pre-retirement receipt must
    # not renew, release, or edit the item's next claim.
    with pytest.raises(BacklogStaleFence):
        await store.renew_claim(item.item_id, fence_token=claimed.fence_token, lease_seconds=100)
    with pytest.raises(BacklogStaleFence):
        await store.release_claim(item.item_id, fence_token=claimed.fence_token)
    with pytest.raises(BacklogStaleFence):
        await store.update(
            item.item_id,
            expected_version=again.version,
            changes={"status": "implemented"},
            fence_token=claimed.fence_token,
        )


async def test_claim_needs_a_claimant_and_a_positive_lease(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(ValueError, match="claimant"):
        await store.claim(item.item_id)
    with pytest.raises(ValueError, match="lease_seconds"):
        await store.claim(item.item_id, principal_id="p", lease_seconds=0)
    with pytest.raises(ValueError, match="lease_seconds"):
        await store.renew_claim(item.item_id, fence_token=1, lease_seconds=-5)
    with pytest.raises(BacklogItemNotFound):
        await store.claim("missing", principal_id="p")
    with pytest.raises(BacklogItemNotFound):
        await store.active_claim("missing")


async def test_renew_and_release_refuse_when_no_claim_is_live(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    with pytest.raises(BacklogClaimRefused):
        await store.renew_claim(item.item_id, fence_token=1, lease_seconds=100)
    with pytest.raises(BacklogClaimRefused):
        await store.release_claim(item.item_id, fence_token=1)
    assert await store.active_claim(item.item_id) is None


async def test_concurrent_claims_have_one_winner_on_every_backend(backend) -> None:
    store = await backend.store()
    project_id = await _workspace(backend, store, "ws-a")
    item = await store.create(_item("ws-a", project_id))

    results = await asyncio.gather(
        *(store.claim(item.item_id, principal_id=f"p-{n}") for n in range(4)),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, BacklogItem)]
    losers = [result for result in results if isinstance(result, BacklogClaimHeld)]
    assert len(winners) == 1
    assert len(losers) == 3
    assert await store.active_claim(item.item_id) == BacklogClaim(
        item_id=item.item_id,
        claimant_principal_id=winners[0].claimant_principal_id,
        fence_token=winners[0].fence_token,
        lease_expires_at=winners[0].lease_expires_at,
    )


async def test_sqlite_restart_keeps_the_claim_and_continues_the_fence(tmp_path) -> None:
    """Claims are durable state like any other field: a restart cannot forget
    who holds an item, and the fence continues from the stored generation."""
    backend = _SqliteBackend(tmp_path)
    try:
        store = await backend.store()
        project_id = await _workspace(backend, store, "ws-a")
        item = await store.create(_item("ws-a", project_id))
        at = _at(offset=-2000)
        claimed = await store.claim(item.item_id, principal_id="holder", at=at, lease_seconds=900)

        reopened = await backend.reopen()
        live = await reopened.active_claim(item.item_id, at=at + timedelta(seconds=100))
        assert live == BacklogClaim(
            item_id=item.item_id,
            claimant_principal_id="holder",
            fence_token=1,
            lease_expires_at=claimed.lease_expires_at,
        )
        # Expired by now: the item is eligible again, and the fence continues.
        retaken = await reopened.claim(item.item_id, agent_id="agent-9")
        assert retaken.fence_token == 2
        with pytest.raises(BacklogStaleFence):
            await reopened.update(
                item.item_id,
                expected_version=retaken.version,
                changes={"title": "stale holder"},
                fence_token=1,
            )
    finally:
        await backend.close()
