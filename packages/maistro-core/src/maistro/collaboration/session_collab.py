"""In-memory session collaboration: co-ownership, presence, and a live event stream.

``SessionCollaboration`` is the core primitive behind "Google Docs for agent work":

- **Co-ownership** — a session has members with graded roles (viewer/editor/owner);
  owners manage membership. The last owner cannot be removed or demoted.
- **Presence** — join / heartbeat / leave; each member's state (active/idle/away)
  is derived from time since last seen.
- **Live stream** — every membership, presence, and message change publishes a
  ``CollabEvent`` that is appended to a bounded per-session history and fanned out
  to live subscribers (drive an SSE/WebSocket "shared view" off ``subscribe``,
  using ``history`` for backlog — the standard Last-Event-ID replay pattern).

Async, single-event-loop (consistent with ``InMemorySessionStore``). Persistence
and multi-tenant hardening are Stronghold concerns; core keeps the session-scope
primitive.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable

from maistro.collaboration.types import (
    Action,
    CollabEvent,
    LastOwnerError,
    Member,
    PermissionDenied,
    Presence,
    PresenceState,
    Role,
    role_permits,
)

# Sentinel pushed onto a subscriber's queue to end its stream (e.g. on revoke).
# Queues carry ``CollabEvent | None`` so the generator can distinguish it.
_CLOSE: None = None


class SessionCollaboration:
    def __init__(
        self,
        *,
        idle_after: float = 60.0,
        away_after: float = 300.0,
        history_limit: int = 512,
        subscriber_queue_limit: int = 256,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._idle_after = idle_after
        self._away_after = away_after
        self._history_limit = history_limit
        self._subscriber_queue_limit = subscriber_queue_limit
        self._clock = clock
        self._members: dict[str, dict[str, Member]] = {}
        self._last_seen: dict[str, dict[str, float]] = {}
        self._history: dict[str, deque[CollabEvent]] = {}
        # session_id -> user_id -> live subscriber queues, so a revoked user's
        # streams can be found and closed rather than kept fed.
        self._subscribers: dict[str, dict[str, set[asyncio.Queue[CollabEvent | None]]]] = {}
        self._seq: dict[str, int] = {}

    # --- membership / co-ownership ---------------------------------------

    async def create(self, session_id: str, owner: str) -> Member:
        """Create the collaboration record for a session with ``owner`` as OWNER."""
        member = Member(user_id=owner, role=Role.OWNER, added_by=owner, added_at=self._clock())
        self._members.setdefault(session_id, {})[owner] = member
        await self._publish(session_id, "created", owner, {"role": Role.OWNER})
        return member

    async def share(self, session_id: str, actor: str, target: str, role: Role) -> Member:
        """Grant ``target`` a role on the session. Requires MANAGE.

        Re-sharing an existing member overwrites their role, so it goes through the
        same last-owner guard as ``set_role`` — otherwise a duplicate invite like
        ``share(actor=alice, target=alice, role=VIEWER)`` could demote the only
        owner and strand the session with no one able to manage it.
        """
        self.require(session_id, actor, Action.MANAGE)
        members = self._members.setdefault(session_id, {})
        existing = members.get(target)
        if existing is not None and existing.role is Role.OWNER and role is not Role.OWNER:
            self._guard_last_owner(session_id, target)
        member = Member(user_id=target, role=role, added_by=actor, added_at=self._clock())
        members[target] = member
        await self._publish(session_id, "shared", actor, {"target": target, "role": role})
        return member

    async def set_role(self, session_id: str, actor: str, target: str, role: Role) -> Member:
        """Change ``target``'s role. Requires MANAGE; keeps at least one owner."""
        self.require(session_id, actor, Action.MANAGE)
        members = self._members.get(session_id, {})
        if target not in members:
            raise PermissionDenied(target, Action.VIEW, session_id)
        if members[target].role is Role.OWNER and role is not Role.OWNER:
            self._guard_last_owner(session_id, target)
        member = Member(
            user_id=target, role=role, added_by=actor, added_at=members[target].added_at
        )
        members[target] = member
        await self._publish(session_id, "role_changed", actor, {"target": target, "role": role})
        return member

    async def revoke(self, session_id: str, actor: str, target: str) -> None:
        """Remove ``target`` from the session. Requires MANAGE; keeps at least one owner."""
        self.require(session_id, actor, Action.MANAGE)
        members = self._members.get(session_id, {})
        if target not in members:
            return
        if members[target].role is Role.OWNER:
            self._guard_last_owner(session_id, target)
        del members[target]
        self._last_seen.get(session_id, {}).pop(target, None)
        # End the revoked user's live streams immediately so they stop receiving
        # events (their access is gone, not just their membership row).
        self._close_subscribers(session_id, target)
        await self._publish(session_id, "revoked", actor, {"target": target})

    def members(self, session_id: str) -> list[Member]:
        return list(self._members.get(session_id, {}).values())

    def role_of(self, session_id: str, user_id: str) -> Role | None:
        member = self._members.get(session_id, {}).get(user_id)
        return member.role if member is not None else None

    def can(self, session_id: str, user_id: str, action: Action) -> bool:
        role = self.role_of(session_id, user_id)
        return role is not None and role_permits(role, action)

    def require(self, session_id: str, user_id: str, action: Action) -> None:
        if not self.can(session_id, user_id, action):
            raise PermissionDenied(user_id, action, session_id)

    # --- presence --------------------------------------------------------

    async def join(self, session_id: str, user_id: str) -> None:
        self.require(session_id, user_id, Action.VIEW)
        self._last_seen.setdefault(session_id, {})[user_id] = self._clock()
        await self._publish(session_id, "joined", user_id, {})

    async def heartbeat(self, session_id: str, user_id: str) -> None:
        self.require(session_id, user_id, Action.VIEW)
        # Publish a presence event when this heartbeat reactivates an idle/away
        # collaborator, so live shared-view clients update rather than showing
        # stale presence until they poll.
        prior = self._presence_state(session_id, user_id)
        self._last_seen.setdefault(session_id, {})[user_id] = self._clock()
        if prior is not None and prior is not PresenceState.ACTIVE:
            await self._publish(session_id, "presence", user_id, {"state": PresenceState.ACTIVE})

    async def leave(self, session_id: str, user_id: str) -> None:
        seen = self._last_seen.get(session_id, {})
        # Only announce a departure for a user who was actually present — else any
        # caller reaching this primitive could fan out spoofed 'left' events for
        # arbitrary users and mislead presence consumers.
        if user_id not in seen:
            return
        seen.pop(user_id, None)
        await self._publish(session_id, "left", user_id, {})

    def _presence_state(self, session_id: str, user_id: str) -> PresenceState | None:
        last = self._last_seen.get(session_id, {}).get(user_id)
        if last is None:
            return None
        age = self._clock() - last
        if age >= self._away_after:
            return PresenceState.AWAY
        if age >= self._idle_after:
            return PresenceState.IDLE
        return PresenceState.ACTIVE

    def presence(self, session_id: str) -> list[Presence]:
        out: list[Presence] = []
        for user_id, last in self._last_seen.get(session_id, {}).items():
            state = self._presence_state(session_id, user_id)
            assert state is not None  # user_id is in _last_seen by construction
            out.append(Presence(user_id=user_id, state=state, last_seen=last))
        return out

    # --- activity feed ---------------------------------------------------

    async def post_message(self, session_id: str, actor: str, content: str) -> CollabEvent:
        """Post a collaborator message to the shared feed. Requires EDIT."""
        self.require(session_id, actor, Action.EDIT)
        return await self._publish(
            session_id, "message", actor, {"content": content, "id": uuid.uuid4().hex}
        )

    def history(self, session_id: str, user_id: str, *, after_seq: int = 0) -> list[CollabEvent]:
        """Replay the session backlog (message contents included). Requires VIEW —
        the same gate as ``subscribe``, so the Last-Event-ID replay path can't leak
        prior events to a caller who only knows the session id."""
        self.require(session_id, user_id, Action.VIEW)
        return [e for e in self._history.get(session_id, deque()) if e.seq > after_seq]

    async def subscribe(self, session_id: str, user_id: str) -> AsyncIterator[CollabEvent]:
        """Yield live events for a session. Requires VIEW. Use ``history`` for backlog.

        The stream ends if the user is revoked (a close sentinel is delivered) or
        loses VIEW; each event is re-checked against current permission before being
        yielded, so access removal takes effect immediately.
        """
        self.require(session_id, user_id, Action.VIEW)
        queue: asyncio.Queue[CollabEvent | None] = asyncio.Queue(
            maxsize=self._subscriber_queue_limit
        )
        self._subscribers.setdefault(session_id, {}).setdefault(user_id, set()).add(queue)
        try:
            while True:
                item = await queue.get()
                # `item is None`, not `item is _CLOSE`: both are the same check
                # (`_CLOSE` *is* None), but narrowing against the literal is what
                # lets a type checker drop `None` from the yielded type. Comparing
                # against the alias leaves this generator inferred as yielding
                # `CollabEvent | None`, contradicting its `AsyncIterator[CollabEvent]`
                # signature. `_CLOSE` stays the name used when *sending* the
                # sentinel, where it reads as intent rather than as a value.
                if item is None or not self.can(session_id, user_id, Action.VIEW):
                    break
                yield item
        finally:
            user_queues = self._subscribers.get(session_id, {}).get(user_id)
            if user_queues is not None:
                user_queues.discard(queue)

    # --- internals -------------------------------------------------------

    def _guard_last_owner(self, session_id: str, target: str) -> None:
        owners = [m for m in self._members.get(session_id, {}).values() if m.role is Role.OWNER]
        if len(owners) <= 1 and any(m.user_id == target for m in owners):
            raise LastOwnerError(f"cannot remove/demote the last owner of {session_id!r}")

    def _close_subscribers(self, session_id: str, user_id: str) -> None:
        for queue in self._subscribers.get(session_id, {}).pop(user_id, set()):
            self._offer(queue, _CLOSE)

    @staticmethod
    def _offer(queue: asyncio.Queue[CollabEvent | None], item: CollabEvent | None) -> None:
        """Enqueue ``item``, dropping the oldest event if the subscriber's bounded
        queue is full. A stalled/disconnected subscriber therefore can't grow
        process memory without bound; it just misses events and can resync via
        ``history(after_seq=...)``."""
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()  # drop oldest to make room
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(item)

    async def _publish(
        self, session_id: str, kind: str, actor: str, data: dict[str, object]
    ) -> CollabEvent:
        seq = self._seq.get(session_id, 0) + 1
        self._seq[session_id] = seq
        event = CollabEvent(
            session_id=session_id,
            kind=kind,
            actor=actor,
            seq=seq,
            ts=self._clock(),
            data=dict(data),
        )
        history = self._history.setdefault(session_id, deque(maxlen=self._history_limit))
        history.append(event)
        for user_queues in list(self._subscribers.get(session_id, {}).values()):
            for queue in list(user_queues):
                self._offer(queue, event)
        return event
