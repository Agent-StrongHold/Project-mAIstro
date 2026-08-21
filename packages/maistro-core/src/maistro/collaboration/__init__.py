"""Session co-ownership / collaboration — "Google Docs for agent work".

Multi-owner sessions with graded roles, presence, and a live event stream, in the
session scope. See ``SessionCollaboration``.
"""

from __future__ import annotations

from maistro.collaboration.session_collab import SessionCollaboration
from maistro.collaboration.types import (
    Action,
    CollabEvent,
    CollaborationError,
    LastOwnerError,
    Member,
    PermissionDenied,
    Presence,
    PresenceState,
    Role,
    role_permits,
)

__all__ = [
    "Action",
    "CollabEvent",
    "CollaborationError",
    "LastOwnerError",
    "Member",
    "PermissionDenied",
    "Presence",
    "PresenceState",
    "Role",
    "SessionCollaboration",
    "role_permits",
]
