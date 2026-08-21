"""Tests for session co-ownership, presence, and the live event stream."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from maistro.collaboration import (
    Action,
    LastOwnerError,
    PermissionDenied,
    PresenceState,
    Role,
    SessionCollaboration,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def test_owner_can_share_and_grades_permissions():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")

    assert collab.role_of("s", "alice") is Role.OWNER
    await collab.share("s", actor="alice", target="bob", role=Role.EDITOR)
    await collab.share("s", actor="alice", target="carol", role=Role.VIEWER)

    assert collab.can("s", "bob", Action.EDIT) is True
    assert collab.can("s", "bob", Action.MANAGE) is False
    assert collab.can("s", "carol", Action.EDIT) is False
    assert collab.can("s", "carol", Action.VIEW) is True


async def test_non_owner_cannot_manage():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    await collab.share("s", actor="alice", target="bob", role=Role.EDITOR)

    with pytest.raises(PermissionDenied):
        await collab.share("s", actor="bob", target="mallory", role=Role.OWNER)


async def test_non_member_has_no_access():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    assert collab.role_of("s", "stranger") is None
    assert collab.can("s", "stranger", Action.VIEW) is False
    with pytest.raises(PermissionDenied):
        collab.require("s", "stranger", Action.VIEW)


async def test_last_owner_cannot_be_revoked_or_demoted():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")

    with pytest.raises(LastOwnerError):
        await collab.revoke("s", actor="alice", target="alice")
    with pytest.raises(LastOwnerError):
        await collab.set_role("s", actor="alice", target="alice", role=Role.EDITOR)

    # With a second owner, the first can step down.
    await collab.share("s", actor="alice", target="bob", role=Role.OWNER)
    await collab.set_role("s", actor="alice", target="alice", role=Role.EDITOR)
    assert collab.role_of("s", "alice") is Role.EDITOR


async def test_presence_states_derive_from_last_seen():
    clock = _Clock()
    collab = SessionCollaboration(idle_after=60, away_after=300, clock=clock)
    await collab.create("s", owner="alice")
    await collab.join("s", "alice")

    assert collab.presence("s")[0].state is PresenceState.ACTIVE
    clock.t += 120  # past idle threshold
    assert collab.presence("s")[0].state is PresenceState.IDLE
    clock.t += 300  # past away threshold
    assert collab.presence("s")[0].state is PresenceState.AWAY

    await collab.heartbeat("s", "alice")  # refreshes
    assert collab.presence("s")[0].state is PresenceState.ACTIVE


async def test_history_and_message_feed_require_edit():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    await collab.share("s", actor="alice", target="carol", role=Role.VIEWER)

    with pytest.raises(PermissionDenied):
        await collab.post_message("s", actor="carol", content="hi")

    await collab.post_message("s", actor="alice", content="hello team")
    kinds = [e.kind for e in collab.history("s", "alice")]
    assert kinds[0] == "created" and "shared" in kinds and kinds[-1] == "message"
    # after_seq filters the backlog
    tail = collab.history("s", "alice", after_seq=1)
    assert all(e.seq > 1 for e in tail)


async def test_live_subscribe_receives_published_events():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    agen = collab.subscribe("s", "alice")

    async def first_event():
        return await agen.__anext__()

    task = asyncio.ensure_future(first_event())
    await asyncio.sleep(0)  # let the subscriber register
    await collab.post_message("s", actor="alice", content="live!")

    event = await asyncio.wait_for(task, timeout=1.0)
    assert event.kind == "message" and event.data["content"] == "live!"
    await agen.aclose()


async def test_subscribe_requires_view():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    with pytest.raises(PermissionDenied):
        agen = collab.subscribe("s", "stranger")
        await agen.__anext__()


async def test_revoke_editor_and_noop_on_non_member():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    await collab.share("s", actor="alice", target="bob", role=Role.EDITOR)

    await collab.revoke("s", actor="alice", target="bob")
    assert collab.role_of("s", "bob") is None
    # revoking someone who isn't a member is a no-op (no raise, no event).
    before = len(collab.history("s", "alice"))
    await collab.revoke("s", actor="alice", target="ghost")
    assert len(collab.history("s", "alice")) == before


async def test_set_role_on_non_member_denied():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    with pytest.raises(PermissionDenied):
        await collab.set_role("s", actor="alice", target="ghost", role=Role.EDITOR)


async def test_revoke_non_last_owner_and_change_non_owner_role():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    await collab.share("s", actor="alice", target="bob", role=Role.OWNER)
    await collab.share("s", actor="alice", target="carol", role=Role.EDITOR)

    # Revoking an owner that isn't the last owner is allowed.
    await collab.revoke("s", actor="alice", target="bob")
    assert collab.role_of("s", "bob") is None

    # Changing a non-owner's role skips the last-owner guard entirely.
    await collab.set_role("s", actor="alice", target="carol", role=Role.VIEWER)
    assert collab.role_of("s", "carol") is Role.VIEWER


async def test_leave_updates_presence_and_publishes():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    await collab.join("s", "alice")
    assert collab.presence("s")

    await collab.leave("s", "alice")
    assert collab.presence("s") == []
    assert collab.history("s", "alice")[-1].kind == "left"


async def test_reshare_cannot_demote_last_owner():
    # A duplicate invite for the only owner must not silently strand the session.
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    with pytest.raises(LastOwnerError):
        await collab.share("s", actor="alice", target="alice", role=Role.VIEWER)
    assert collab.role_of("s", "alice") is Role.OWNER


async def test_leave_for_non_present_user_is_noop():
    # A caller can't fan out a spoofed 'left' event for a user who never joined.
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    before = len(collab.history("s", "alice"))
    await collab.leave("s", "ghost")
    assert len(collab.history("s", "alice")) == before


async def test_history_requires_view():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    with pytest.raises(PermissionDenied):
        collab.history("s", "stranger")


async def test_heartbeat_publishes_presence_on_reactivation():
    clock = _Clock()
    collab = SessionCollaboration(idle_after=60, away_after=300, clock=clock)
    await collab.create("s", owner="alice")
    await collab.join("s", "alice")
    clock.t += 120  # go idle
    assert collab.presence("s")[0].state is PresenceState.IDLE

    before = len(collab.history("s", "alice"))
    await collab.heartbeat("s", "alice")  # reactivate
    events = collab.history("s", "alice")
    assert len(events) == before + 1
    assert events[-1].kind == "presence" and events[-1].data["state"] is PresenceState.ACTIVE

    # A heartbeat while already active does not spam presence events.
    steady = len(collab.history("s", "alice"))
    await collab.heartbeat("s", "alice")
    assert len(collab.history("s", "alice")) == steady


async def test_revoke_ends_live_subscriber_stream():
    collab = SessionCollaboration()
    await collab.create("s", owner="alice")
    await collab.share("s", actor="alice", target="bob", role=Role.VIEWER)

    agen = collab.subscribe("s", "bob")
    collected: list[str] = []

    async def drain() -> None:
        async for event in agen:
            collected.append(event.kind)

    task = asyncio.ensure_future(drain())
    await asyncio.sleep(0)  # register the subscriber
    await collab.revoke("s", actor="alice", target="bob")
    # The close sentinel ends the generator; the post-revoke message never arrives.
    await asyncio.wait_for(task, timeout=1.0)
    await collab.post_message("s", actor="alice", content="after")
    assert "message" not in collected


async def test_subscriber_queue_is_bounded():
    # A registered but non-consuming subscriber must not grow without bound: its
    # queue caps at the configured limit, dropping oldest events.
    collab = SessionCollaboration(subscriber_queue_limit=8)
    await collab.create("s", owner="alice")

    sub = collab.subscribe("s", "alice")
    task = asyncio.ensure_future(sub.__anext__())
    await asyncio.sleep(0)  # run the generator to queue.get(), registering the queue

    # post_message doesn't yield to the loop, so the parked getter never drains:
    # all events pile into the bounded queue, which drops oldest past its cap.
    for i in range(100):
        await collab.post_message("s", actor="alice", content=str(i))

    queues = collab._subscribers["s"]["alice"]
    assert queues and all(q.qsize() <= 8 for q in queues)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
        await task
    await sub.aclose()
