"""Canonical Workspace BacklogItem work-source (#82).

BacklogItem is portfolio/work-source/acceptance/control-plane state -- not a
Goal, not a scheduler, and not RSI infrastructure. See ``model.py`` for the
boundary statement and ``store.py`` for the one contract all three backends
(memory, SQLite, PostgreSQL) implement.
"""

from maistro.backlog.model import (
    BacklogClaim,
    BacklogClaimError,
    BacklogClosure,
    BacklogClosureError,
    BacklogEvent,
    BacklogEventKind,
    BacklogItem,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogVersionConflict,
)
from maistro.backlog.store import (
    DEFAULT_LEASE_SECONDS,
    UNSET,
    BacklogStore,
    InMemoryBacklogStore,
)

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "UNSET",
    "BacklogClaim",
    "BacklogClaimError",
    "BacklogClosure",
    "BacklogClosureError",
    "BacklogEvent",
    "BacklogEventKind",
    "BacklogItem",
    "BacklogItemNotFound",
    "BacklogItemStatus",
    "BacklogStore",
    "BacklogVersionConflict",
    "InMemoryBacklogStore",
]
