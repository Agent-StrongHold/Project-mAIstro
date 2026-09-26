"""Workspace BacklogItem service: the public work-source contract (#98).

Consumers -- the persistent Workspace Agent (#804), RSI (#50), the UI --
depend on `BacklogItemStore` and `BacklogItem` from here, never on a backend.
"""

from maistro.workspaces.backlog.model import (
    BacklogItem,
    BacklogItemAlreadyExists,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogRelationError,
    BacklogVersionConflict,
    GoalReference,
)
from maistro.workspaces.backlog.store import BacklogItemStore, InMemoryBacklogItemStore

__all__ = [
    "BacklogItem",
    "BacklogItemAlreadyExists",
    "BacklogItemNotFound",
    "BacklogItemStatus",
    "BacklogItemStore",
    "BacklogRelationError",
    "BacklogVersionConflict",
    "GoalReference",
    "InMemoryBacklogItemStore",
]
