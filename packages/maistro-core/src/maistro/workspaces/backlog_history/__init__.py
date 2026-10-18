"""Workspace BacklogItem history: the append-only provenance contract (#101).

Consumers — the persistent Workspace Agent (#804), reconcilers (#805/#806),
the UI — depend on `BacklogHistoryStore` and `BacklogHistoryEvent` from here,
never on a backend. History references canonical state (Goals #458, Runs,
reconciliation decisions); it never duplicates their authority, and it never
constitutes an execution lifecycle of its own.
"""

from maistro.workspaces.backlog_history.model import (
    DISCOVERED_INITIAL_STATUS,
    BacklogEventAlreadyExists,
    BacklogHistoryError,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    ClosureEvidenceMissing,
    FieldChange,
    GoalLink,
    ReconciliationReference,
    RunReference,
)
from maistro.workspaces.backlog_history.recording import BacklogSubject
from maistro.workspaces.backlog_history.store import (
    BacklogHistoryStore,
    InMemoryBacklogHistoryStore,
)

__all__ = [
    "DISCOVERED_INITIAL_STATUS",
    "BacklogEventAlreadyExists",
    "BacklogHistoryError",
    "BacklogHistoryEvent",
    "BacklogHistoryEventKind",
    "BacklogHistoryStore",
    "BacklogSubject",
    "ClosureEvidenceMissing",
    "FieldChange",
    "GoalLink",
    "InMemoryBacklogHistoryStore",
    "ReconciliationReference",
    "RunReference",
]
