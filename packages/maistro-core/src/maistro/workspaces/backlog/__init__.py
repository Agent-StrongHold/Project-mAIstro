"""Workspace BacklogItem service: the public work-source contract (#98).

Consumers -- the persistent Workspace Agent (#804), RSI (#50), the UI --
depend on `BacklogItemStore` and `BacklogItem` from here, never on a backend.

#100 adds the claim service on the same contract: an atomic, fenced lease on
the right to progress one item. Humans, the persistent Workspace Agent,
delegated Agents and later RSI all claim through these store methods (or the
HTTP routes over them); a claim is coordination, never Goal ownership, and it
never touches the canonical Goal -> Graph -> Run spine.
"""

from maistro.workspaces.backlog.model import (
    AGENT_CLAIMABLE_AUTONOMY_MODES,
    CLAIMABLE_STATUSES,
    DEFAULT_LEASE_SECONDS,
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
from maistro.workspaces.backlog.store import BacklogItemStore, InMemoryBacklogItemStore

__all__ = [
    "AGENT_CLAIMABLE_AUTONOMY_MODES",
    "CLAIMABLE_STATUSES",
    "DEFAULT_LEASE_SECONDS",
    "BacklogClaim",
    "BacklogClaimHeld",
    "BacklogClaimRefused",
    "BacklogItem",
    "BacklogItemAlreadyExists",
    "BacklogItemNotFound",
    "BacklogItemStatus",
    "BacklogItemStore",
    "BacklogRelationError",
    "BacklogStaleFence",
    "BacklogVersionConflict",
    "GoalReference",
    "InMemoryBacklogItemStore",
]
