"""Types for session co-ownership / collaboration ("Google Docs for agent work").

A session can be co-owned by multiple users with graded roles; collaborators see
each other's presence and a live event stream. This lives in the ``session`` scope
(CLAUDE.md: global -> team -> user -> agent -> session) — no ``org_id`` in core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Graded session roles, least → most privileged."""

    VIEWER = "viewer"  # read + follow the live stream
    EDITOR = "editor"  # + post messages / drive the agent
    OWNER = "owner"  # + manage members (share / revoke / change roles)


class Action(StrEnum):
    VIEW = "view"
    EDIT = "edit"
    MANAGE = "manage"


_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.EDITOR: 1, Role.OWNER: 2}
_MIN_ROLE: dict[Action, Role] = {
    Action.VIEW: Role.VIEWER,
    Action.EDIT: Role.EDITOR,
    Action.MANAGE: Role.OWNER,
}


def role_permits(role: Role, action: Action) -> bool:
    return _RANK[role] >= _RANK[_MIN_ROLE[action]]


class PresenceState(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    AWAY = "away"


@dataclass(frozen=True)
class Member:
    user_id: str
    role: Role
    added_by: str = ""
    added_at: float = 0.0


@dataclass(frozen=True)
class Presence:
    user_id: str
    state: PresenceState
    last_seen: float


@dataclass(frozen=True)
class CollabEvent:
    """One entry in a session's collaboration activity stream."""

    session_id: str
    kind: str  # created | shared | revoked | role_changed | joined | left | message
    actor: str
    seq: int
    ts: float
    data: dict[str, Any] = field(default_factory=dict)


class CollaborationError(Exception):
    """Base class for collaboration errors."""


class PermissionDenied(CollaborationError):
    def __init__(self, user_id: str, action: Action, session_id: str) -> None:
        super().__init__(f"user {user_id!r} may not {action} session {session_id!r}")
        self.user_id = user_id
        self.action = action
        self.session_id = session_id


class LastOwnerError(CollaborationError):
    """Raised when an operation would leave a session with no owner."""
