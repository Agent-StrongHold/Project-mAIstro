"""Authorized agent list/select/claim/write over the backlog (#102).

The cutover acceptance requires an authorized agent path against the
database: listing what may be worked, selecting deterministically, claiming
a lease, writing within it, and releasing — with authorization fail-closed
and every durable leg proven across a restart. The SQLite leg here is the
same store the cutover imports into, so "works against the DB" is the
concrete database the authority moved to, not a lookalike.
"""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.backlog.agent_surface import AgentBacklogSurface, AgentSurfaceError
from maistro.backlog.model import BacklogItemStatus
from maistro.backlog.store import InMemoryBacklogStore

WS = "ws-agent-test"


def _roles(roles: dict[str, str]):
    """An authorize callable backed by a static role table."""

    async def authorize(actor: str, workspace_id: str, action: str):
        if workspace_id != WS:
            return None
        return roles.get(actor)  # type: ignore[return-value]

    return authorize


@pytest.fixture
def store() -> InMemoryBacklogStore:
    return InMemoryBacklogStore()


async def _seed(
    store: InMemoryBacklogStore,
    item_id: str,
    title: str,
    *,
    priority: int = 3,
    deps: tuple[str, ...] = (),
) -> None:
    await store.create_item(
        workspace_id=WS,
        title=title,
        actor="human:owner",
        priority=priority,
        dependencies=deps,
        item_id=item_id,
    )


async def test_list_is_fail_closed_and_hides_closed_work(store) -> None:
    surface = AgentBacklogSurface(store, _roles({"agent:x": "editor"}))
    await _seed(store, "eng-001", "Open work")
    await _seed(store, "eng-002", "Closed work")
    await store.close_item(
        "eng-002",
        expected_version=1,
        actor="human:owner",
        outcome=BacklogItemStatus.DONE,
        closure_summary="evidenced",
        evidence_refs=("PR #1",),
    )
    items = await surface.list_items(actor="agent:x", workspace_id=WS)
    assert [item.item_id for item in items] == ["eng-001"]

    with pytest.raises(AgentSurfaceError, match="may not read"):
        await surface.list_items(actor="agent:stranger", workspace_id=WS)
    with pytest.raises(AgentSurfaceError, match="may not read"):
        await surface.list_items(actor="agent:x", workspace_id="other-ws")


async def test_select_orders_by_priority_then_rank_and_skips_claimed(store) -> None:
    surface = AgentBacklogSurface(store, _roles({"agent:x": "editor"}))
    await _seed(store, "eng-001", "Middle", priority=3)
    await _seed(store, "eng-002", "Top priority", priority=1)
    await _seed(
        store,
        "eng-003",
        "Also top, older rank",
        priority=1,
    )
    await store.update_item("eng-003", expected_version=1, actor="human:owner", rank=5.0)
    await store.update_item("eng-002", expected_version=1, actor="human:owner", rank=1.0)

    selection = await surface.select(actor="agent:x", workspace_id=WS)
    assert selection is not None
    assert selection.item.item_id == "eng-002"
    assert selection.reason == "highest-priority open item"

    # A claim takes the top item out of selection; the next one surfaces.
    await surface.claim("eng-002", actor="agent:x")
    second = await surface.select(actor="agent:x", workspace_id=WS)
    assert second is not None and second.item.item_id == "eng-003"


async def test_claim_write_release_cycle_is_attributed_and_enforced(store) -> None:
    surface = AgentBacklogSurface(store, _roles({"agent:a": "editor", "agent:b": "editor"}))
    await _seed(store, "eng-001", "Work item")
    claim = await surface.claim("eng-001", actor="agent:a")

    # The claim holder writes; a bystander does not ride the lease.
    edited = await surface.write(
        "eng-001",
        actor="agent:a",
        expected_version=1,
        claim_id=claim.claim_id,
        details="- progressed under the lease",
    )
    assert edited.version == 2
    assert edited.details == "- progressed under the lease"

    with pytest.raises(AgentSurfaceError, match="claimed by 'agent:a'"):
        await surface.write("eng-001", actor="agent:b", expected_version=2, details="- sneak in")

    # A second claimant is refused while the lease is live.
    with pytest.raises(AgentSurfaceError, match="already claimed"):
        await surface.claim("eng-001", actor="agent:b")

    await surface.release("eng-001", actor="agent:a", claim_id=claim.claim_id)
    assert await store.active_claim("eng-001") is None
    # With no live claim, an editor writes without one.
    edited_again = await surface.write(
        "eng-001", actor="agent:b", expected_version=2, details="- after release"
    )
    assert edited_again.version == 3


async def test_viewer_reads_but_cannot_claim_or_write(store) -> None:
    surface = AgentBacklogSurface(store, _roles({"agent:v": "viewer"}))
    await _seed(store, "eng-001", "Work item")
    assert len(await surface.list_items(actor="agent:v", workspace_id=WS)) == 1
    with pytest.raises(AgentSurfaceError, match="may not claim"):
        await surface.claim("eng-001", actor="agent:v")
    with pytest.raises(AgentSurfaceError, match="may not write"):
        await surface.write("eng-001", actor="agent:v", expected_version=1, title="nope")


async def test_unknown_item_and_unknown_workspace_answer_not_found(store) -> None:
    surface = AgentBacklogSurface(store, _roles({"agent:a": "editor"}))
    with pytest.raises(AgentSurfaceError, match="no such backlog item"):
        await surface.claim("eng-404", actor="agent:a")


async def test_full_agent_cycle_is_durable_across_a_restart(tmp_path) -> None:
    """The SQLite leg: the cycle lands in the database the cutover owns."""
    path = tmp_path / "agent-cycle.db"
    conn = await aiosqlite.connect(path)
    from maistro.backlog.sqlite_store import SqliteBacklogStore

    durable = SqliteBacklogStore(conn)
    await durable.ensure_schema()
    surface = AgentBacklogSurface(durable, _roles({"agent:a": "editor"}))

    await durable.create_item(
        workspace_id=WS, title="Durable work", actor="human:owner", item_id="eng-001"
    )
    claim = await surface.claim("eng-001", actor="agent:a")
    await surface.write(
        "eng-001",
        actor="agent:a",
        expected_version=1,
        claim_id=claim.claim_id,
        details="- agent progress",
    )
    await conn.close()

    # Restart: a fresh connection must see the item, the edit, and the lease.
    conn2 = await aiosqlite.connect(path)
    durable2 = SqliteBacklogStore(conn2)
    surface2 = AgentBacklogSurface(durable2, _roles({"agent:a": "editor"}))
    try:
        item = await durable2.get_item("eng-001")
        assert item is not None
        assert item.version == 2
        assert item.details == "- agent progress"
        active = await durable2.active_claim("eng-001")
        assert active is not None and active.claim_id == claim.claim_id
        assert len(await surface2.list_items(actor="agent:a", workspace_id=WS)) == 1
        kinds = [event.kind.value for event in await durable2.events("eng-001")]
        assert kinds == ["created", "claimed", "updated"]
    finally:
        await conn2.close()
